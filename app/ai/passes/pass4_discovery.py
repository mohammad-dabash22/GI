"""Pass 4: Cross-document relationship discovery on the canonical (post-merge) graph."""

from app.config import FAST_MODEL
from app.ai.client import call_llm, parse_json
from app.ai.passes.pass2_crossref import _build_entity_summary, _build_relationship_summary
from app.ai.prompts.cross_reference import CROSS_REL_SYSTEM, CROSS_REL_USER


def pass4_discover_connections(
    canonical_entities: list[dict],
    canonical_relationships: list[dict],
    file_texts: dict[str, str],
    progress_cb=None,
) -> dict:
    """For each document, ask the model for missed links using the full canonical graph as context.

    Returns new_entities, new_relationships (to be merged and validated by the orchestrator), and errors.
    """
    errors: list[str] = []
    new_entities: list[dict] = []
    new_relationships: list[dict] = []
    if not file_texts:
        return {
            "new_entities": new_entities,
            "new_relationships": new_relationships,
            "errors": errors,
        }

    entity_summary = _build_entity_summary(canonical_entities)
    relationship_summary = _build_relationship_summary(canonical_relationships)

    filenames = list(file_texts.keys())
    n = len(filenames)
    for i, fname in enumerate(filenames):
        text = file_texts[fname]
        if len(text) > 150000:
            text = text[:150000] + "\n[...truncated...]"

        user = CROSS_REL_USER.format(
            entity_list=entity_summary,
            relationship_list=relationship_summary,
            filename=fname,
            text=text,
        )

        try:
            print(f"[PASS4] Cross-document discovery in {fname}...")
            raw = call_llm(CROSS_REL_SYSTEM, user, model=FAST_MODEL, max_tokens=4096)
            data = parse_json(raw)
            for e in data.get("new_entities", []):
                e["source"] = fname
                new_entities.append(e)
            for r in data.get("new_relationships", []):
                r["source"] = fname
                new_relationships.append(r)
            print(
                f"[PASS4] {fname}: {len(data.get('new_entities', []))} new entities, "
                f"{len(data.get('new_relationships', []))} new rels"
            )
        except Exception as e:
            errors.append(f"Pass 4 error ({fname}): {e}")
        if progress_cb:
            progress_cb("pass4", i + 1, n)

    return {
        "new_entities": new_entities,
        "new_relationships": new_relationships,
        "errors": errors,
    }
