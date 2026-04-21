"""Pass 2: Cross-reference — entity deduplication and cross-document relationship discovery."""

from app.config import FAST_MODEL
from app.ai.client import call_llm, parse_json
from app.ai.prompts.dedup import DEDUP_SYSTEM, DEDUP_USER
from app.ai.prompts.cross_reference import CROSS_REL_SYSTEM, CROSS_REL_USER


def _build_entity_summary(entities: list[dict]) -> str:
    """Build a text summary of entities for LLM consumption."""
    lines = []
    for i, e in enumerate(entities):
        eid = e.get("id", e.get("name", f"entity_{i}").lower().replace(" ", "_"))
        props = ", ".join(f"{k}={v}" for k, v in e.get("properties", {}).items())
        lines.append(
            f"  - ID={eid} | Type={e.get('type', '')} | Name={e.get('name', '')} "
            f"| Source={e.get('source', '')} | Props={props}"
        )
    return "\n".join(lines)


def pass2_cross_reference(entities: list[dict], relationships: list[dict],
                          file_texts: dict[str, str],
                          existing_entities: list[dict] | None = None,
                          progress_cb=None) -> dict:
    """Pass 2: Two-step cross-reference — (a) dedup entities, (b) find cross-doc relationships."""
    errors = []

    # ── 2a: Entity deduplication ──
    entity_summary = _build_entity_summary(entities)
    merges = []
    try:
        user = DEDUP_USER.format(entity_list=entity_summary)
        print(f"[PASS2a] Calling LLM for entity deduplication ({len(entities)} entities)...")
        raw = call_llm(DEDUP_SYSTEM, user, model=FAST_MODEL, max_tokens=4096)
        data = parse_json(raw)
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
    context_entities = kept_entities.copy()
    if existing_entities:
        context_entities.extend(existing_entities)
    entity_summary = _build_entity_summary(context_entities)
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
            raw = call_llm(CROSS_REL_SYSTEM, user, model=FAST_MODEL, max_tokens=4096)
            data = parse_json(raw)
            for e in data.get("new_entities", []):
                e["source"] = fname
                new_entities.append(e)
            for r in data.get("new_relationships", []):
                r["source"] = fname
                new_relationships.append(r)
            print(f"[PASS2b] {fname}: {len(data.get('new_entities', []))} new entities, "
                  f"{len(data.get('new_relationships', []))} new rels")
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
