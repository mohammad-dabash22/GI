"""Converts extracted entities and relationships into graph data for both 2D (vis.js) and 3D (3d-force-graph).

Styles are imported from the domain layer rather than defined inline.
"""

from app.domain.entity_types import ENTITY_STYLES, DEFAULT_NODE_STYLE
from app.domain.relationship_types import (
    EDGE_STYLES, DEFAULT_EDGE_STYLE,
    MONEY_TYPES, CONTROL_TYPES, WEAK_TYPES,
)


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
        style = ENTITY_STYLES.get(etype, DEFAULT_NODE_STYLE)
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
        style = EDGE_STYLES.get(rtype, DEFAULT_EDGE_STYLE)

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
        if rtype in MONEY_TYPES:
            opacity = 1.0
        elif rtype in CONTROL_TYPES:
            opacity = 0.85
        elif rtype in WEAK_TYPES:
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
            "properties": props,
            "startDate": props.get("start_date", ""),
            "endDate": props.get("end_date", ""),
        })

    return {"nodes": nodes, "links": links}
