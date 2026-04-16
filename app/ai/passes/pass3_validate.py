"""Pass 3: Validation and confidence scoring."""

import json
from concurrent.futures import ThreadPoolExecutor

from app.config import FAST_MODEL, MAX_CONCURRENT_CALLS
from app.ai.client import call_llm, parse_json
from app.ai.prompts.validation import VALIDATION_SYSTEM, VALIDATION_USER

_executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_CALLS)


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
            raw = call_llm(VALIDATION_SYSTEM, user, model=FAST_MODEL, max_tokens=4096)
            data = parse_json(raw)
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
