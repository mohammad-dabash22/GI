"""Extraction pipeline: Pass 1 (extract) -> Pass 2 (dedup) -> Pass 3 (validate) -> post-process.

Cross-document discovery (Pass 4) runs after merge with the global graph; see run_cross_document_discovery.
"""

from app.ai.passes.pass1_extract import pass1_quick_extract, _build_source_tag
from app.ai.passes.pass2_crossref import pass2_dedup
from app.ai.passes.pass3_validate import pass3_validate
from app.ai.passes.pass4_discovery import pass4_discover_connections
from app.ai.postprocess import post_process
from app.ai.prompts.extraction import BASE_SYSTEM
from app.ai.client import call_llm, parse_json


def extract_full_pipeline(
    files_data: list[dict],
    progress_cb=None,
) -> dict:
    """Run Pass 1-3 plus post-process on the upload batch (no global merge, no Pass 4).

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

    # ── Pass 2 (batch dedup only) ──
    p2 = pass2_dedup(
        all_entities, all_relationships,
        progress_cb=progress_cb
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
    all_entities, all_relationships = post_process(all_entities, all_relationships)

    return {
        "entities": all_entities,
        "relationships": all_relationships,
        "errors": all_errors,
        "pass": 3,
        "pass1_result": pass1_result,
        "pass2_result": pass2_result,
    }


def run_cross_document_discovery(
    canonical_entities: list[dict],
    canonical_relationships: list[dict],
    file_texts: dict[str, str],
    progress_cb=None,
) -> dict:
    """Pass 4: post-merge cross-document discovery, validate new artifacts, post-process, return graph.

    Does not perform deduplicate_entities; caller should run global dedup before save.
    """
    p4 = pass4_discover_connections(
        canonical_entities, canonical_relationships, file_texts,
        progress_cb=progress_cb
    )
    new_entities = p4.get("new_entities", [])
    new_rels = p4.get("new_relationships", [])
    all_errors: list = list(p4.get("errors", []))

    if new_entities or new_rels:
        p3 = pass3_validate(
            new_entities, new_rels,
            progress_cb=None,
        )
        new_entities = p3["entities"]
        new_rels = p3["relationships"]
        all_errors.extend(p3.get("errors", []))

    combined_entities = list(canonical_entities) + new_entities
    combined_rels = list(canonical_relationships) + new_rels
    combined_entities, combined_rels = post_process(combined_entities, combined_rels)

    # Deduplicate edges by (from_id, to_id, type) after merge
    rel_seen = set()
    deduped_rels: list[dict] = []
    for r in combined_rels:
        key = (r.get("from_id"), r.get("to_id"), r.get("type"))
        if key not in rel_seen:
            rel_seen.add(key)
            deduped_rels.append(r)

    return {
        "entities": combined_entities,
        "relationships": deduped_rels,
        "errors": all_errors,
    }


# ── Legacy single-pass (kept for backward compatibility) ──

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
            raw = call_llm(system, user_msg, max_tokens=4000)
            data = parse_json(raw)
            for e in data.get("entities", []):
                e["source"] = source
            for r in data.get("relationships", []):
                r["source"] = source
            all_entities.extend(data.get("entities", []))
            all_relationships.extend(data.get("relationships", []))
        except Exception as e:
            errors.append(f"Error processing {source}: {e}")

    return {"entities": all_entities, "relationships": all_relationships, "errors": errors}
