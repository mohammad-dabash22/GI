import hashlib
import json
import re
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from config import (
    FAST_MODEL, STRONG_MODEL, FALLBACK_MODEL,
    MAX_CONCURRENT_CALLS, ENTITY_TYPES, RELATIONSHIP_TYPES,
    AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_KEY,
    AZURE_OPENAI_API_VERSION, AZURE_OPENAI_DEPLOYMENT,
)
from prompts import (
    DOCUMENT_TYPE_PROMPTS, BASE_SYSTEM,
    DEDUP_SYSTEM, DEDUP_USER,
    CROSS_REL_SYSTEM, CROSS_REL_USER,
    VALIDATION_SYSTEM, VALIDATION_USER,
)

_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_CALLS)

_azure_client = None


def _get_client():
    """Return a singleton AzureOpenAI client."""
    global _azure_client
    if _azure_client is None:
        import httpx, ssl
        from openai import AzureOpenAI
        ssl_ctx = ssl.create_default_context()
        http_client = httpx.Client(verify=ssl_ctx)
        _azure_client = AzureOpenAI(
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_key=AZURE_OPENAI_KEY,
            api_version=AZURE_OPENAI_API_VERSION,
            http_client=http_client,
        )
    return _azure_client


def _call_llm(system: str, user: str, model: str = None,
              max_tokens: int = 4096) -> str:
    """Call Azure OpenAI."""
    model = model or FAST_MODEL
    client = _get_client()
    print(f"[LLM] Calling {model} ({len(user)} chars input)...")
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        max_completion_tokens=max_tokens,
    )
    print(f"[LLM] {model} responded OK")
    return resp.choices[0].message.content.strip()


def _parse_json(raw: str) -> dict:
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _build_source_tag(filename: str, chunk: dict) -> str:
    parts = []
    if "page" in chunk:
        parts.append(f"Page {chunk['page']}")
    if "paragraph" in chunk:
        parts.append(f"Paragraph {chunk['paragraph']}")
    if "line_start" in chunk:
        parts.append(f"Lines {chunk['line_start']}-{chunk['line_end']}")
    return f"{filename}:{','.join(parts)}" if parts else filename


# ═══════════════════════════════════════════════════════════════
# PASS 1 - Quick Extract (parallel, type-specific prompts)
# ═══════════════════════════════════════════════════════════════

def _extract_chunk(filename: str, chunk: dict, doc_type: str) -> dict:
    system = DOCUMENT_TYPE_PROMPTS.get(doc_type, BASE_SYSTEM)
    source = _build_source_tag(filename, chunk)

    location_parts = []
    if "page" in chunk:
        location_parts.append(f"Page {chunk['page']}")
    if "paragraph" in chunk:
        location_parts.append(f"Paragraph {chunk['paragraph']}")
    if "line_start" in chunk:
        location_parts.append(f"Lines {chunk['line_start']}-{chunk['line_end']}")
    location = ", ".join(location_parts) or "Unknown"

    user = (
        f"Extract all entities and relationships from this document section.\n\n"
        f"Source file: {filename}\nDocument type: {doc_type}\nLocation: {location}\n\n"
        f"IMPORTANT: For the 'evidence' field, quote the EXACT sentence(s) from the text below. "
        f"Prefix with the specific line reference, e.g. 'Line 5: Viktor Petrov is the CEO'. "
        f"Do NOT cite the entire range '{location}' -- cite only the specific line(s).\n\n"
        f"--- DOCUMENT TEXT ---\n{chunk['text']}\n--- END ---\n\n"
        f"Return valid JSON only."
    )

    try:
        print(f"[EXTRACT] Calling LLM for {source} ...")
        raw = _call_llm(system, user, model=FAST_MODEL, max_tokens=4096)
        print(f"[EXTRACT] Got response for {source} ({len(raw)} chars)")
        data = _parse_json(raw)
        for e in data.get("entities", []):
            e["source"] = source
        for r in data.get("relationships", []):
            r["source"] = source
        print(f"[EXTRACT] {source}: {len(data.get('entities',[]))} entities, {len(data.get('relationships',[]))} rels")
        return data
    except Exception as e:
        print(f"[EXTRACT ERROR] {source}: {type(e).__name__}: {e}")
        return {"entities": [], "relationships": [], "errors": [f"Chunk error ({source}): {e}"]}


def _make_doc_prefix(filename: str, chunk_idx: int) -> str:
    h = hashlib.md5(filename.encode()).hexdigest()[:4]
    return f"{h}_c{chunk_idx}"


def _namespace_ids(data: dict, prefix: str) -> dict:
    """Add prefix to all entity IDs and remap relationship from_id/to_id."""
    id_map = {}
    for e in data.get("entities", []):
        old_id = e.get("id", "")
        if old_id:
            new_id = f"{prefix}_{old_id}"
            id_map[old_id] = new_id
            e["id"] = new_id
    for r in data.get("relationships", []):
        fid = r.get("from_id", "")
        tid = r.get("to_id", "")
        if fid in id_map:
            r["from_id"] = id_map[fid]
        if tid in id_map:
            r["to_id"] = id_map[tid]
    return data


def pass1_quick_extract(filename: str, chunks: list[dict], doc_type: str,
                        progress_cb=None) -> dict:
    """Pass 1: Fast parallel extraction with type-specific prompts."""
    all_entities, all_relationships, errors = [], [], []

    def _process(chunk_idx, chunk):
        return chunk_idx, _extract_chunk(filename, chunk, doc_type)

    futures = []
    for ci, chunk in enumerate(chunks):
        futures.append(_executor.submit(_process, ci, chunk))

    for i, future in enumerate(futures):
        try:
            chunk_idx, result = future.result(timeout=120)
            prefix = _make_doc_prefix(filename, chunk_idx)
            result = _namespace_ids(result, prefix)
            for e in result.get("entities", []):
                if not e.get("id"):
                    e["id"] = f"{prefix}_ent_{len(all_entities)}"
            all_entities.extend(result.get("entities", []))
            all_relationships.extend(result.get("relationships", []))
            errors.extend(result.get("errors", []))
        except Exception as e:
            errors.append(f"Chunk {i} failed: {e}")
        if progress_cb:
            progress_cb("pass1", i + 1, len(futures))

    return {"entities": all_entities, "relationships": all_relationships, "errors": errors}


# ═══════════════════════════════════════════════════════════════
# PASS 2 - Cross-Reference & Resolve
# ═══════════════════════════════════════════════════════════════

def _build_entity_summary(entities: list[dict]) -> str:
    lines = []
    for i, e in enumerate(entities):
        eid = e.get("id", e.get("name", f"entity_{i}").lower().replace(" ", "_"))
        props = ", ".join(f"{k}={v}" for k, v in e.get("properties", {}).items())
        lines.append(
            f"  - ID={eid} | Type={e.get('type','')} | Name={e.get('name','')} "
            f"| Source={e.get('source','')} | Props={props}"
        )
    return "\n".join(lines)


def pass2_cross_reference(entities: list[dict], relationships: list[dict],
                          file_texts: dict[str, str],
                          progress_cb=None) -> dict:
    """Pass 2: Two-step cross-reference -- (a) dedup entities, (b) find cross-doc relationships."""
    errors = []

    # ── 2a: Entity deduplication ──
    entity_summary = _build_entity_summary(entities)
    merges = []
    try:
        user = DEDUP_USER.format(entity_list=entity_summary)
        print(f"[PASS2a] Calling LLM for entity deduplication ({len(entities)} entities)...")
        raw = _call_llm(DEDUP_SYSTEM, user,
                        model=FAST_MODEL, max_tokens=4096)
        data = _parse_json(raw)
        merges = data.get("merges", [])
        print(f"[PASS2a] Found {len(merges)} merges")
    except Exception as e:
        errors.append(f"Dedup error: {e}")

    if progress_cb:
        progress_cb("pass2", 1, 2)

    # Apply merges
    merge_map = {}
    for m in merges:
        merge_map[m.get("merge_id", "")] = m.get("keep_id", "")

    for r in relationships:
        if r.get("from_id", "") in merge_map:
            r["from_id"] = merge_map[r["from_id"]]
        if r.get("to_id", "") in merge_map:
            r["to_id"] = merge_map[r["to_id"]]

    merged_ids = set(merge_map.keys())
    kept_entities = [e for e in entities if e.get("id") not in merged_ids]

    # ── 2b: Cross-document relationships ──
    entity_summary = _build_entity_summary(kept_entities)
    new_entities, new_relationships = [], []
    filenames = list(file_texts.keys())
    for i, fname in enumerate(filenames):
        text = file_texts[fname]
        if len(text) > 150000:
            text = text[:150000] + "\n[...truncated...]"

        user = CROSS_REL_USER.format(
            entity_list=entity_summary,
            filename=fname,
            text=text
        )

        try:
            print(f"[PASS2b] Checking cross-doc relationships in {fname}...")
            raw = _call_llm(CROSS_REL_SYSTEM, user,
                            model=FAST_MODEL, max_tokens=4096)
            data = _parse_json(raw)
            for e in data.get("new_entities", []):
                e["source"] = fname
                new_entities.append(e)
            for r in data.get("new_relationships", []):
                r["source"] = fname
                new_relationships.append(r)
            print(f"[PASS2b] {fname}: {len(data.get('new_entities',[]))} new entities, {len(data.get('new_relationships',[]))} new rels")
        except Exception as e:
            errors.append(f"Cross-ref error ({fname}): {e}")

    kept_entities.extend(new_entities)
    all_rels = relationships + new_relationships

    # Dedup relationships
    seen = set()
    deduped_rels = []
    for r in all_rels:
        key = (r.get("from_id"), r.get("to_id"), r.get("type"))
        if key not in seen:
            seen.add(key)
            deduped_rels.append(r)

    if progress_cb:
        progress_cb("pass2", 2, 2)

    return {
        "entities": kept_entities,
        "relationships": deduped_rels,
        "merges_applied": len(merges),
        "errors": errors
    }


# ═══════════════════════════════════════════════════════════════
# PASS 3 - Validation & Confidence Scoring
# ═══════════════════════════════════════════════════════════════

def pass3_validate(entities: list[dict], relationships: list[dict],
                   progress_cb=None) -> dict:
    """Pass 3: Validate each extraction with reasoned confidence scores."""
    errors = []

    # Build validation items in batches of 12
    all_items = []
    for i, e in enumerate(entities):
        if not e.get("id"):
            e["id"] = e.get("name", f"entity_{i}").lower().replace(" ", "_")
        all_items.append({
            "id": e["id"],
            "kind": "entity",
            "name": e.get("name", ""),
            "type": e.get("type", ""),
            "evidence": e.get("evidence", ""),
            "source": e.get("source", ""),
        })
    for i, r in enumerate(relationships):
        all_items.append({
            "id": f"rel_{i}",
            "kind": "relationship",
            "from": r.get("from_id", r.get("from", "")),
            "to": r.get("to_id", r.get("to", "")),
            "type": r.get("type", ""),
            "label": r.get("label", ""),
            "evidence": r.get("evidence", ""),
            "source": r.get("source", ""),
        })

    batch_size = 12
    validations = {}
    batches = [all_items[i:i+batch_size] for i in range(0, len(all_items), batch_size)]

    def _validate_batch(batch):
        items_text = json.dumps(batch, indent=2)
        user = VALIDATION_USER.format(items=items_text)
        try:
            raw = _call_llm(VALIDATION_SYSTEM, user,
                            model=FAST_MODEL, max_tokens=4096)
            data = _parse_json(raw)
            return data.get("validations", [])
        except Exception as e:
            return [{"error": str(e)}]

    futures = [_executor.submit(_validate_batch, b) for b in batches]
    for i, future in enumerate(futures):
        try:
            results = future.result(timeout=60)
            for v in results:
                if "id" in v:
                    validations[v["id"]] = v
        except Exception as e:
            errors.append(f"Validation batch {i} failed: {e}")
        if progress_cb:
            progress_cb("pass3", i + 1, len(batches))

    # Apply validation results
    for e in entities:
        v = validations.get(e.get("id", ""))
        if v:
            e["confidence"] = v.get("confidence", e.get("confidence", "medium"))
            e["confidence_score"] = v.get("score", 5)
            e["confidence_reason"] = v.get("reason", "")

    for i, r in enumerate(relationships):
        v = validations.get(f"rel_{i}")
        if v:
            r["confidence"] = v.get("confidence", r.get("confidence", "medium"))
            r["confidence_score"] = v.get("score", 5)
            r["confidence_reason"] = v.get("reason", "")

    return {
        "entities": entities,
        "relationships": relationships,
        "validations_count": len(validations),
        "errors": errors
    }


# ═══════════════════════════════════════════════════════════════
# Post-processing cleanup
# ═══════════════════════════════════════════════════════════════

_JUNK_ENTITY_PATTERNS = re.compile(
    r'^(charter fees?|equipment lease?|demurrage credit|rental income|'
    r'director loan|loan repayment|refund|consulting|commission|'
    r'capital (contribution|call)|profit distribution|investment return|'
    r'intercompany loan|account maintenance|wire transfer|'
    r'opening balance|closing balance|quarterly fee|'
    r'[\d,.]+ ?(pounds?|gbp|usd|eur|sar|aed))$',
    re.IGNORECASE
)


def _post_process(entities: list[dict], relationships: list[dict]) -> tuple[list[dict], list[dict]]:
    """Remove junk entities and dangling relationships."""
    entity_ids = {e["id"] for e in entities}

    # Remove junk entities (transaction descriptions that slipped through)
    cleaned_entities = []
    removed_ids = set()
    for e in entities:
        name = (e.get("name") or "").strip()
        etype = e.get("type", "")
        # Remove MoneyTransfer entities with generic description names
        if etype == "MoneyTransfer" and len(name.split()) <= 4 and not re.search(r'\d{4,}', name):
            if _JUNK_ENTITY_PATTERNS.match(name):
                removed_ids.add(e["id"])
                print(f"[CLEANUP] Removed junk entity: {name} ({etype})")
                continue
        # Remove entities with very short generic names
        if len(name) <= 2 and etype not in ("Phone", "Email"):
            removed_ids.add(e["id"])
            continue
        cleaned_entities.append(e)

    # Remove relationships pointing to removed entities
    valid_ids = {e["id"] for e in cleaned_entities}
    entity_type_map = {e["id"]: e.get("type", "") for e in cleaned_entities}
    cleaned_rels = []
    for r in relationships:
        fid = r.get("from_id", "")
        tid = r.get("to_id", "")
        if fid not in valid_ids or tid not in valid_ids or fid == tid:
            continue
        rtype = r.get("type", "")
        # Remove structurally impossible: Location -> traveled_to -> Location
        if rtype == "traveled_to" and entity_type_map.get(fid) == "Location":
            print(f"[CLEANUP] Removed Location->traveled_to->Location: {fid} -> {tid}")
            continue
        # Remove structurally impossible: Location -> transferred_money_to -> Location
        if rtype == "transferred_money_to" and entity_type_map.get(fid) == "Location" and entity_type_map.get(tid) == "Location":
            print(f"[CLEANUP] Removed Location->transferred_money_to->Location: {fid} -> {tid}")
            continue
        # Remove low-confidence relationships (score <= 3) flagged by validation
        if r.get("confidence_score", 10) <= 3:
            print(f"[CLEANUP] Removed low-confidence relationship: {fid} -[{rtype}]-> {tid} (score={r.get('confidence_score')})")
            continue
        # Truncate overly long labels and move full text to evidence
        label = r.get("label", "")
        if len(label) > 80:
            if not r.get("evidence"):
                r["evidence"] = label
            r["label"] = label[:60].rsplit(" ", 1)[0] + "..."
        cleaned_rels.append(r)

    # Remove orphan entities -- only keep disconnected Document/Event/Location (reference value)
    _KEEP_ORPHAN_TYPES = {"Document", "Event", "Location"}
    connected_ids = set()
    for r in cleaned_rels:
        connected_ids.add(r.get("from_id", ""))
        connected_ids.add(r.get("to_id", ""))

    final_entities = []
    for e in cleaned_entities:
        if e["id"] in connected_ids:
            final_entities.append(e)
        elif e.get("type", "") in _KEEP_ORPHAN_TYPES and e.get("confidence") == "high":
            final_entities.append(e)
        else:
            print(f"[CLEANUP] Removed orphan entity: {e.get('name', '')} ({e.get('type', '')})")

    print(f"[CLEANUP] Final: {len(final_entities)} entities, {len(cleaned_rels)} relationships "
          f"(removed {len(entities) - len(final_entities)} entities, "
          f"{len(relationships) - len(cleaned_rels)} relationships)")

    return final_entities, cleaned_rels


# ═══════════════════════════════════════════════════════════════
# Full pipeline (synchronous, called from background thread)
# ═══════════════════════════════════════════════════════════════

def extract_full_pipeline(
    files_data: list[dict],
    progress_cb=None
) -> dict:
    """Run the complete 3-pass pipeline.
    files_data: list of {"filename": str, "chunks": list, "doc_type": str, "full_text": str}
    progress_cb: fn(pass_name, current, total) for progress updates
    """
    all_entities, all_relationships, all_errors = [], [], []

    # ── Pass 1 ──
    for fd in files_data:
        result = pass1_quick_extract(
            fd["filename"], fd["chunks"], fd["doc_type"],
            progress_cb
        )
        all_entities.extend(result["entities"])
        all_relationships.extend(result["relationships"])
        all_errors.extend(result.get("errors", []))

    pass1_result = {
        "entities": list(all_entities),
        "relationships": list(all_relationships),
        "errors": list(all_errors),
        "pass": 1
    }

    # ── Pass 2 ──
    file_texts = {fd["filename"]: fd["full_text"] for fd in files_data}
    p2 = pass2_cross_reference(
        all_entities, all_relationships, file_texts,
        progress_cb
    )
    all_entities = p2["entities"]
    all_relationships = p2["relationships"]
    all_errors.extend(p2.get("errors", []))

    pass2_result = {
        "entities": list(all_entities),
        "relationships": list(all_relationships),
        "errors": list(all_errors),
        "pass": 2,
        "merges_applied": p2.get("merges_applied", 0)
    }

    # ── Pass 3 ──
    p3 = pass3_validate(
        all_entities, all_relationships,
        progress_cb
    )
    all_entities = p3["entities"]
    all_relationships = p3["relationships"]
    all_errors.extend(p3.get("errors", []))

    # ── Post-processing cleanup ──
    all_entities, all_relationships = _post_process(all_entities, all_relationships)

    return {
        "entities": all_entities,
        "relationships": all_relationships,
        "errors": all_errors,
        "pass": 3,
        "pass1_result": pass1_result,
        "pass2_result": pass2_result,
    }


# ═══════════════════════════════════════════════════════════════
# Legacy single-pass (kept for backward compatibility)
# ═══════════════════════════════════════════════════════════════

def extract_from_document(filename: str, chunks: list[dict]) -> dict:
    """Legacy single-pass extraction."""
    all_entities, all_relationships, errors = [], [], []

    for chunk in chunks:
        source = _build_source_tag(filename, chunk)
        system = BASE_SYSTEM
        location_parts = []
        if "page" in chunk:
            location_parts.append(f"Page {chunk['page']}")
        if "paragraph" in chunk:
            location_parts.append(f"Paragraph {chunk['paragraph']}")
        if "line_start" in chunk:
            location_parts.append(f"Lines {chunk['line_start']}-{chunk['line_end']}")
        location = ", ".join(location_parts) or "Unknown"
        user_msg = (f"Extract all entities and relationships.\n\n"
                    f"Source: {filename}\nLocation: {location}\n\n"
                    f"--- TEXT ---\n{chunk['text']}\n--- END ---\n\nReturn valid JSON only.")
        try:
            raw = _call_llm(system, user_msg, max_tokens=4000)
            data = _parse_json(raw)
            for e in data.get("entities", []):
                e["source"] = source
            for r in data.get("relationships", []):
                r["source"] = source
            all_entities.extend(data.get("entities", []))
            all_relationships.extend(data.get("relationships", []))
        except Exception as e:
            errors.append(f"Error processing {source}: {e}")

    return {"entities": all_entities, "relationships": all_relationships, "errors": errors}
