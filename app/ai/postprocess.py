"""Post-processing cleanup: removes junk entities, orphans, and structurally impossible relationships."""

import re


_JUNK_ENTITY_PATTERNS = re.compile(
    r'^(charter fees?|equipment lease?|demurrage credit|rental income|'
    r'director loan|loan repayment|refund|consulting|commission|'
    r'capital (contribution|call)|profit distribution|investment return|'
    r'intercompany loan|account maintenance|wire transfer|'
    r'opening balance|closing balance|quarterly fee|'
    r'[\d,.]+ ?(pounds?|gbp|usd|eur|sar|aed))$',
    re.IGNORECASE
)

# Orphan entities of these types are kept if high-confidence (reference value)
_KEEP_ORPHAN_TYPES = {"Document", "Event", "Location"}


def post_process(entities: list[dict], relationships: list[dict]) -> tuple[list[dict], list[dict]]:
    """Remove junk entities and dangling relationships."""

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
