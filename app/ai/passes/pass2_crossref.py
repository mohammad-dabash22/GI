"""Pass 2: Entity deduplication within the current upload batch (LLM merge decisions).

Cross-document relationship discovery runs in Pass 4 after global merge; see pass4_discovery.
"""

from app.config import FAST_MODEL
from app.ai.client import call_llm, parse_json
from app.ai.prompts.dedup import DEDUP_SYSTEM, DEDUP_USER


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


def _build_relationship_summary(relationships: list[dict]) -> str:
    """Build a text summary of relationships for LLM consumption."""
    if not relationships:
        return "  (none)"
    lines = []
    for r in relationships:
        label = r.get("label") or r.get("type", "")
        lines.append(
            f"  - {r.get('from_id')} --[{r.get('type')}]--> {r.get('to_id')} | Label={label}"
        )
    return "\n".join(lines)


def pass2_dedup(
    entities: list[dict],
    relationships: list[dict],
    progress_cb=None,
) -> dict:
    """Pass 2: LLM-based entity deduplication for the current batch; apply merges to rels.

    Returns entities with merged rows removed, relationships with IDs remapped, and edges deduped.
    """
    errors = []

    entity_summary = _build_entity_summary(entities)
    merges = []
    try:
        user = DEDUP_USER.format(entity_list=entity_summary)
        print(f"[PASS2] Calling LLM for entity deduplication ({len(entities)} entities)...")
        raw = call_llm(DEDUP_SYSTEM, user, model=FAST_MODEL, max_tokens=4096)
        data = parse_json(raw)
        merges = data.get("merges", [])
        print(f"[PASS2] Found {len(merges)} merges")
    except Exception as e:
        errors.append(f"Dedup error: {e}")

    if progress_cb:
        progress_cb("pass2", 1, 1)

    # Apply merges
    merge_map: dict[str, str] = {}
    for m in merges:
        merge_map[m.get("merge_id", "")] = m.get("keep_id", "")

    for r in relationships:
        if r.get("from_id", "") in merge_map:
            r["from_id"] = merge_map[r["from_id"]]
        if r.get("to_id", "") in merge_map:
            r["to_id"] = merge_map[r["to_id"]]

    merged_ids = set(merge_map.keys())
    kept_entities = [e for e in entities if e.get("id") not in merged_ids]

    # Dedup relationships
    seen = set()
    deduped_rels: list[dict] = []
    for r in relationships:
        key = (r.get("from_id"), r.get("to_id"), r.get("type"))
        if key not in seen:
            seen.add(key)
            deduped_rels.append(r)

    return {
        "entities": kept_entities,
        "relationships": deduped_rels,
        "merges_applied": len(merges),
        "errors": errors,
    }
