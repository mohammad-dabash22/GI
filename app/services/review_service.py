"""Review service: accept, reject, and restore extracted items for analyst review."""

from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.core.graph_builder import build_graph_data
from app.core.graph_state import load_graph, save_graph, push_undo, require_project
from app.services.audit_service import log_action
from app.services.graph_service import build_graph_response


def get_review_items(project_id: int, threshold: int, db: Session) -> dict:
    """Get entities and relationships below the confidence threshold for review."""
    gs = load_graph(project_id, db)
    items = []
    for e in gs.entities:
        score = e.get("confidence_score", 5)
        if score <= threshold:
            items.append({
                "id": e["id"], "kind": "entity", "name": e.get("name"),
                "type": e.get("type"), "score": score,
                "confidence": e.get("confidence"),
                "reason": e.get("confidence_reason", ""),
                "evidence": e.get("evidence", ""),
                "source": e.get("source", ""),
                "properties": e.get("properties", {}),
            })
    for i, r in enumerate(gs.relationships):
        score = r.get("confidence_score", 5)
        if score <= threshold:
            fn = next((e["name"] for e in gs.entities if e["id"] == r["from_id"]), r["from_id"])
            tn = next((e["name"] for e in gs.entities if e["id"] == r["to_id"]), r["to_id"])
            items.append({
                "id": f"edge_{i}", "kind": "relationship",
                "name": f"{fn} -> {tn}",
                "type": r.get("type"), "label": r.get("label"),
                "score": score, "confidence": r.get("confidence"),
                "reason": r.get("confidence_reason", ""),
                "evidence": r.get("evidence", ""),
                "source": r.get("source", ""),
                "properties": r.get("properties", {}),
            })
    items.sort(key=lambda x: x.get("score", 5))
    return {"items": items, "total": len(items)}


def accept_item(project_id: int, item_id: str, username: str, db: Session) -> dict:
    """Accept a review item by promoting its confidence to high."""
    require_project(project_id, db)
    gs = load_graph(project_id, db)
    rejected = gs.rejected_items
    push_undo(project_id, gs.entities, gs.relationships, rejected)

    if item_id.startswith("edge_"):
        idx = int(item_id.replace("edge_", ""))
        if 0 <= idx < len(gs.relationships):
            gs.relationships[idx]["confidence"] = "high"
            gs.relationships[idx]["confidence_score"] = 10
    else:
        for e in gs.entities:
            if e["id"] == item_id:
                e["confidence"] = "high"
                e["confidence_score"] = 10
                break

    save_graph(project_id, gs.entities, gs.relationships, gs.errors, db,
               rejected_items=rejected)
    log_action("review_accept", user=username, details={"item_id": item_id})
    return build_graph_response(gs.entities, gs.relationships)


def reject_item(project_id: int, item_id: str, username: str, db: Session) -> dict:
    """Reject a review item, removing it from the active graph and archiving it."""
    require_project(project_id, db)
    gs = load_graph(project_id, db)
    rejected = gs.rejected_items
    push_undo(project_id, gs.entities, gs.relationships, rejected)

    eid_name = {e["id"]: e.get("name", e["id"]) for e in gs.entities}
    removed_item = None

    if item_id.startswith("edge_"):
        idx = int(item_id.replace("edge_", ""))
        if 0 <= idx < len(gs.relationships):
            removed_item = gs.relationships.pop(idx)
            removed_item["_rejected_kind"] = "relationship"
            removed_item["_from_name"] = eid_name.get(removed_item.get("from_id", ""), removed_item.get("from_id", ""))
            removed_item["_to_name"] = eid_name.get(removed_item.get("to_id", ""), removed_item.get("to_id", ""))
    else:
        for e in gs.entities:
            if e["id"] == item_id:
                removed_item = dict(e)
                removed_item["_rejected_kind"] = "entity"
                break
        gs.entities[:] = [e for e in gs.entities if e["id"] != item_id]
        if removed_item:
            gs.relationships[:] = [
                r for r in gs.relationships
                if r.get("from_id") != item_id and r.get("to_id") != item_id
            ]

    if removed_item:
        removed_item["_rejected_at"] = datetime.now(timezone.utc).isoformat()
        rejected.append(removed_item)

    save_graph(project_id, gs.entities, gs.relationships, gs.errors, db,
               rejected_items=rejected)
    log_action("review_reject", user=username, details={"item_id": item_id})
    return build_graph_response(gs.entities, gs.relationships)


def get_rejected_items(project_id: int, db: Session) -> dict:
    """Get all rejected items for a project."""
    gs = load_graph(project_id, db)
    rejected = gs.rejected_items
    items = []
    for item in rejected:
        kind = item.get("_rejected_kind", "entity")
        if kind == "entity":
            items.append({
                "kind": "entity",
                "id": item.get("id"),
                "name": item.get("name"),
                "type": item.get("type"),
                "confidence": item.get("confidence"),
                "score": item.get("confidence_score"),
                "evidence": item.get("evidence", ""),
                "source": item.get("source", ""),
                "rejected_at": item.get("_rejected_at", ""),
            })
        else:
            items.append({
                "kind": "relationship",
                "id": item.get("id"),
                "from_name": item.get("_from_name", item.get("from_id", "")),
                "to_name": item.get("_to_name", item.get("to_id", "")),
                "type": item.get("type"),
                "label": item.get("label"),
                "confidence": item.get("confidence"),
                "score": item.get("confidence_score"),
                "evidence": item.get("evidence", ""),
                "source": item.get("source", ""),
                "rejected_at": item.get("_rejected_at", ""),
            })
    return {"items": items, "total": len(items)}


def restore_item(project_id: int, index: int, username: str, db: Session) -> dict:
    """Restore a previously rejected item back into the active graph."""
    require_project(project_id, db)
    gs = load_graph(project_id, db)
    rejected = gs.rejected_items
    push_undo(project_id, gs.entities, gs.relationships, rejected)

    if index < 0 or index >= len(rejected):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid index")

    item = rejected.pop(index)
    kind = item.pop("_rejected_kind", "entity")
    item.pop("_rejected_at", None)
    item.pop("_from_name", None)
    item.pop("_to_name", None)

    if kind == "entity":
        gs.entities.append(item)
    else:
        gs.relationships.append(item)

    save_graph(project_id, gs.entities, gs.relationships, gs.errors, db,
               rejected_items=rejected)
    log_action("review_restore", user=username, details={"index": index})
    return build_graph_response(gs.entities, gs.relationships)
