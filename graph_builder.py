"""Converts extracted entities and relationships into graph data for both 2D (vis.js) and 3D (3d-force-graph)."""

ENTITY_STYLES = {
    "Person":        {"color": "#5B8DEF", "shape": "dot",          "size": 25, "emoji": "\U0001F464"},
    "Organization":  {"color": "#F5A623", "shape": "diamond",      "size": 25, "emoji": "\U0001F3E2"},
    "Account":       {"color": "#7ED321", "shape": "square",       "size": 20, "emoji": "\U0001F4B3"},
    "Phone":         {"color": "#BD10E0", "shape": "triangle",     "size": 20, "emoji": "\U0001F4DE"},
    "Address":       {"color": "#A0785A", "shape": "square",       "size": 18, "emoji": "\U0001F4CD"},
    "Vehicle":       {"color": "#6B7C8A", "shape": "triangle",     "size": 20, "emoji": "\U0001F697"},
    "Email":         {"color": "#4FC1E9", "shape": "dot",          "size": 18, "emoji": "\u2709"},
    "MoneyTransfer": {"color": "#ED5565", "shape": "star",         "size": 22, "emoji": "\U0001F4B5"},
    "Document":      {"color": "#6C7AE0", "shape": "square",       "size": 18, "emoji": "\U0001F4C4"},
    "Event":         {"color": "#E84393", "shape": "diamond",      "size": 20, "emoji": "\U0001F4C5"},
    "Location":      {"color": "#00B894", "shape": "triangleDown", "size": 20, "emoji": "\U0001F30D"},
}

EDGE_STYLES = {
    # Money flows -- red family, thick, particles
    "transferred_money_to": {"color": "#E74C3C", "width": 3,   "dashes": False, "particles": 4},
    "paid_by":              {"color": "#E55B5B", "width": 2.5, "dashes": False, "particles": 3},
    "received_from":        {"color": "#D94040", "width": 2.5, "dashes": False, "particles": 3},
    "financed":             {"color": "#C0392B", "width": 3,   "dashes": False, "particles": 3},
    # Ownership / control -- green family
    "owns":                 {"color": "#27AE60", "width": 2.5, "dashes": False, "particles": 0},
    "controls":             {"color": "#2ECC71", "width": 2.5, "dashes": False, "particles": 0},
    "shareholder_of":       {"color": "#1E8449", "width": 2.5, "dashes": False, "particles": 0},
    "sold_shares_to":       {"color": "#52BE80", "width": 2,   "dashes": False, "particles": 0},
    # Employment / roles -- blue family, each distinct
    "works_for":            {"color": "#5B8DEF", "width": 2,   "dashes": False, "particles": 0},
    "ceo_of":               {"color": "#3A6FD8", "width": 2.5, "dashes": False, "particles": 0},
    "director_of":          {"color": "#4A7FE8", "width": 2,   "dashes": False, "particles": 0},
    "board_member_of":      {"color": "#6E9EF5", "width": 2,   "dashes": False, "particles": 0},
    "managed_by":           {"color": "#85B0F7", "width": 1.5, "dashes": False, "particles": 0},
    # Communication -- purple family, dashed
    "communicated_with":    {"color": "#9B59B6", "width": 2,   "dashes": True,  "particles": 2},
    "met_with":             {"color": "#AF7AC5", "width": 1.5, "dashes": True,  "particles": 0},
    "family":               {"color": "#8E44AD", "width": 2,   "dashes": True,  "particles": 0},
    # Location / registration -- teal/brown, thin dashed
    "located_at":           {"color": "#1ABC9C", "width": 1.5, "dashes": True,  "particles": 0},
    "traveled_to":          {"color": "#16A085", "width": 1.5, "dashes": False, "particles": 0},
    "registered_to":        {"color": "#48C9B0", "width": 1.5, "dashes": False, "particles": 0},
    # Documents / legal -- indigo
    "signed":               {"color": "#6C7AE0", "width": 1.5, "dashes": False, "particles": 0},
    "witnessed":            {"color": "#7D8BE8", "width": 1,   "dashes": True,  "particles": 0},
    # Trade / commerce -- pink
    "trades_with":          {"color": "#E84393", "width": 2,   "dashes": False, "particles": 2},
    # Weak / generic -- grey, thin dashed
    "related_to":           {"color": "#888888", "width": 1,   "dashes": True,  "particles": 0},
    "associated_with":      {"color": "#999999", "width": 1,   "dashes": True,  "particles": 0},
    "referred_by":          {"color": "#777777", "width": 1,   "dashes": True,  "particles": 0},
}

DEFAULT_EDGE = {"color": "#888888", "width": 1, "dashes": True, "particles": 0}
DEFAULT_NODE = ENTITY_STYLES["Person"]


def build_graph_data(entities: list[dict], relationships: list[dict]) -> dict:
    """Build unified graph data usable by both vis.js and 3d-force-graph."""
    entity_ids = {e["id"] for e in entities}

    # Compute degree per entity for hub sizing
    degree = {}
    for rel in relationships:
        fid, tid = rel.get("from_id"), rel.get("to_id")
        if fid in entity_ids and tid in entity_ids:
            degree[fid] = degree.get(fid, 0) + 1
            degree[tid] = degree.get(tid, 0) + 1

    nodes = []
    for entity in entities:
        etype = entity.get("type", "Person")
        style = ENTITY_STYLES.get(etype, DEFAULT_NODE)
        base_size = style["size"]
        hub_bonus = min(degree.get(entity["id"], 0) * 2, 12)

        nodes.append({
            "id": entity["id"],
            "name": entity.get("name", entity["id"]),
            "type": etype,
            "color": style["color"],
            "shape": style["shape"],
            "size": base_size + hub_bonus,
            "emoji": style["emoji"],
            "source": entity.get("source", ""),
            "sources": entity.get("sources", [entity.get("source", "")]),
            "evidence": entity.get("evidence", ""),
            "allEvidence": entity.get("all_evidence", [entity.get("evidence", "")]),
            "properties": entity.get("properties", {}),
            "confidence": entity.get("confidence", "medium"),
            "confidenceScore": entity.get("confidence_score", 5),
            "confidenceReason": entity.get("confidence_reason", ""),
        })

    links = []
    for i, rel in enumerate(relationships):
        if rel.get("from_id") not in entity_ids or rel.get("to_id") not in entity_ids:
            continue
        rtype = rel.get("type", "related_to")
        style = EDGE_STYLES.get(rtype, DEFAULT_EDGE)

        # Build rich multi-line label
        label_parts = [rel.get("label", rtype)]
        props = rel.get("properties", {})
        if props.get("amount"):
            label_parts.append(str(props["amount"]))
        if props.get("percentage"):
            label_parts.append(str(props["percentage"]) + "%")
        if props.get("start_date") or props.get("end_date"):
            date_str = f"{props.get('start_date', '')} - {props.get('end_date', '')}".strip(" -")
            if date_str:
                label_parts.append(date_str)
        rich_label = "\n".join(dict.fromkeys(label_parts))  # dedupe while preserving order

        # Importance-based opacity
        _money_types = {"transferred_money_to","paid_by","received_from","financed"}
        _control_types = {"owns","controls","shareholder_of","sold_shares_to","ceo_of","director_of"}
        _weak_types = {"related_to","associated_with","referred_by"}
        if rtype in _money_types:
            opacity = 1.0
        elif rtype in _control_types:
            opacity = 0.85
        elif rtype in _weak_types:
            opacity = 0.5
        else:
            opacity = 0.75

        links.append({
            "id": f"edge_{i}",
            "source": rel["from_id"],
            "target": rel["to_id"],
            "from": rel["from_id"],
            "to": rel["to_id"],
            "type": rtype,
            "label": rich_label,
            "color": style["color"],
            "width": style["width"],
            "dashes": style["dashes"],
            "particles": style["particles"],
            "opacity": opacity,
            "evidenceSource": rel.get("source", ""),
            "evidence": rel.get("evidence", ""),
            "confidence": rel.get("confidence", "medium"),
            "confidenceScore": rel.get("confidence_score", 5),
            "confidenceReason": rel.get("confidence_reason", ""),
            "startDate": props.get("start_date", ""),
            "endDate": props.get("end_date", ""),
        })

    return {"nodes": nodes, "links": links}
