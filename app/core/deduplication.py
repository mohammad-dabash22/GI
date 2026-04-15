"""String-similarity based entity deduplication."""

import re
from difflib import SequenceMatcher

_LEGAL_SUFFIXES = re.compile(
    r'\b(ltd|limited|inc|incorporated|corp|corporation|llc|llp|'
    r'srl|sa|gmbh|ag|plc|bv|nv|pty|co|company)\b\.?',
    re.IGNORECASE
)

TYPE_THRESHOLDS = {
    "Organization": 0.80,
    "Person": 0.75,
    "Account": 0.85,
    "Location": 0.80,
}
DEFAULT_THRESHOLD = 0.70


def _normalize_name(name: str) -> str:
    """Normalize entity name for comparison: lowercase, strip legal suffixes, extra whitespace."""
    n = name.lower().strip()
    n = _LEGAL_SUFFIXES.sub("", n)
    n = re.sub(r'[.,\-()]+', ' ', n)
    n = re.sub(r'\s+', ' ', n).strip()
    return n


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize_name(a), _normalize_name(b)).ratio()


def deduplicate_entities(entities: list[dict], threshold: float = None) -> tuple[list[dict], dict]:
    """Merge entities that likely refer to the same real-world thing.
    Uses type-aware thresholds. Returns (deduplicated_entities, id_mapping)."""
    if not entities:
        return [], {}

    merged = []
    id_mapping = {}

    for entity in entities:
        matched = False
        etype = entity.get("type", "")
        t = threshold or TYPE_THRESHOLDS.get(etype, DEFAULT_THRESHOLD)

        for existing in merged:
            if etype != existing.get("type"):
                continue
            sim = similarity(entity.get("name", ""), existing.get("name", ""))
            if sim >= t:
                id_mapping[entity["id"]] = existing["id"]
                if "sources" not in existing:
                    existing["sources"] = [existing.get("source", "")]
                existing["sources"].append(entity.get("source", ""))
                if "all_evidence" not in existing:
                    existing["all_evidence"] = [existing.get("evidence", "")]
                existing["all_evidence"].append(entity.get("evidence", ""))
                conf_order = {"high": 3, "medium": 2, "low": 1}
                if conf_order.get(entity.get("confidence"), 0) > conf_order.get(existing.get("confidence"), 0):
                    existing["confidence"] = entity["confidence"]
                for k, v in entity.get("properties", {}).items():
                    if k not in existing.get("properties", {}):
                        existing.setdefault("properties", {})[k] = v
                # Keep the longer (more complete) name
                if len(entity.get("name", "")) > len(existing.get("name", "")):
                    existing["name"] = entity["name"]
                matched = True
                break

        if not matched:
            id_mapping[entity["id"]] = entity["id"]
            merged.append(entity.copy())

    return merged, id_mapping


def remap_relationships(relationships: list[dict], id_mapping: dict) -> list[dict]:
    """Update relationship IDs after entity deduplication, and remove self-loops."""
    remapped = []
    seen = set()
    for rel in relationships:
        new_from = id_mapping.get(rel.get("from_id"), rel.get("from_id"))
        new_to = id_mapping.get(rel.get("to_id"), rel.get("to_id"))
        if new_from == new_to:
            continue
        key = (new_from, new_to, rel.get("type"))
        if key in seen:
            continue
        seen.add(key)
        remapped.append({
            **rel,
            "from_id": new_from,
            "to_id": new_to
        })
    return remapped
