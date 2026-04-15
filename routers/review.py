from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user
from graph_builder import build_graph_data
from audit_log import log_action
from graph_state import load_graph, save_graph, push_undo, require_project
from schemas.graph import ReviewActionRequest, ReviewRestoreRequest

router = APIRouter(prefix="/api")


def _graph_response(entities: list, relationships: list) -> dict:
    return {
        "success": True,
        "graph": build_graph_data(entities, relationships),
        "entity_count": len(entities),
        "relationship_count": len(relationships),
    }


@router.get("/review/items")
async def get_review_items(
    project_id: int = Query(...),
    threshold: int = 10,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    gs = load_graph(project_id, db)
    items = []
    for e in gs["entities"]:
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
    for i, r in enumerate(gs["relationships"]):
        score = r.get("confidence_score", 5)
        if score <= threshold:
            fn = next((e["name"] for e in gs["entities"] if e["id"] == r["from_id"]), r["from_id"])
            tn = next((e["name"] for e in gs["entities"] if e["id"] == r["to_id"]), r["to_id"])
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
    return JSONResponse({"items": items, "total": len(items)})


@router.post("/review/accept")
async def review_accept(
    body: ReviewActionRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_project(body.project_id, db)
    gs = load_graph(body.project_id, db)
    rejected = gs.get("rejected_items", [])
    push_undo(body.project_id, gs["entities"], gs["relationships"], rejected)
    if body.id.startswith("edge_"):
        idx = int(body.id.replace("edge_", ""))
        if 0 <= idx < len(gs["relationships"]):
            gs["relationships"][idx]["confidence"] = "high"
            gs["relationships"][idx]["confidence_score"] = 10
    else:
        for e in gs["entities"]:
            if e["id"] == body.id:
                e["confidence"] = "high"
                e["confidence_score"] = 10
                break
    save_graph(body.project_id, gs["entities"], gs["relationships"], gs["errors"], db,
               rejected_items=rejected)
    log_action("review_accept", user=user.get("username", ""), details={"item_id": body.id})
    return JSONResponse(_graph_response(gs["entities"], gs["relationships"]))


@router.post("/review/reject")
async def review_reject(
    body: ReviewActionRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_project(body.project_id, db)
    gs = load_graph(body.project_id, db)
    rejected = gs.get("rejected_items", [])
    push_undo(body.project_id, gs["entities"], gs["relationships"], rejected)
    eid_name = {e["id"]: e.get("name", e["id"]) for e in gs["entities"]}
    removed_item = None
    if body.id.startswith("edge_"):
        idx = int(body.id.replace("edge_", ""))
        if 0 <= idx < len(gs["relationships"]):
            removed_item = gs["relationships"].pop(idx)
            removed_item["_rejected_kind"] = "relationship"
            removed_item["_from_name"] = eid_name.get(removed_item.get("from_id", ""), removed_item.get("from_id", ""))
            removed_item["_to_name"] = eid_name.get(removed_item.get("to_id", ""), removed_item.get("to_id", ""))
    else:
        for e in gs["entities"]:
            if e["id"] == body.id:
                removed_item = dict(e)
                removed_item["_rejected_kind"] = "entity"
                break
        gs["entities"] = [e for e in gs["entities"] if e["id"] != body.id]
        if removed_item:
            gs["relationships"] = [
                r for r in gs["relationships"]
                if r.get("from_id") != body.id and r.get("to_id") != body.id
            ]
    if removed_item:
        from datetime import datetime, timezone
        removed_item["_rejected_at"] = datetime.now(timezone.utc).isoformat()
        rejected.append(removed_item)
    save_graph(body.project_id, gs["entities"], gs["relationships"], gs["errors"], db,
               rejected_items=rejected)
    log_action("review_reject", user=user.get("username", ""), details={"item_id": body.id})
    return JSONResponse(_graph_response(gs["entities"], gs["relationships"]))


@router.get("/review/rejected")
async def get_rejected_items(
    project_id: int = Query(...),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    gs = load_graph(project_id, db)
    rejected = gs.get("rejected_items", [])
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
    return JSONResponse({"items": items, "total": len(items)})


@router.post("/review/restore")
async def review_restore(
    body: ReviewRestoreRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_project(body.project_id, db)
    gs = load_graph(body.project_id, db)
    rejected = gs.get("rejected_items", [])
    push_undo(body.project_id, gs["entities"], gs["relationships"], rejected)
    if body.index < 0 or body.index >= len(rejected):
        return JSONResponse({"success": False, "error": "Invalid index"}, status_code=400)
    item = rejected.pop(body.index)
    kind = item.pop("_rejected_kind", "entity")
    item.pop("_rejected_at", None)
    item.pop("_from_name", None)
    item.pop("_to_name", None)
    if kind == "entity":
        gs["entities"].append(item)
    else:
        gs["relationships"].append(item)
    save_graph(body.project_id, gs["entities"], gs["relationships"], gs["errors"], db,
               rejected_items=rejected)
    log_action("review_restore", user=user.get("username", ""), details={"index": body.index})
    return JSONResponse(_graph_response(gs["entities"], gs["relationships"]))
