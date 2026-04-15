import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user
from graph_builder import build_graph_data
from audit_log import log_action
from graph_state import load_graph, save_graph, push_undo, pop_undo, require_project
from schemas.graph import (
    ProjectIdRequest,
    CreateNodeRequest,
    DeleteNodeRequest,
    CreateConnectionRequest,
    DeleteConnectionRequest,
    UpdateEntityRequest,
    UpdateEdgeRequest,
    UpdateEvidenceLegacyRequest,
    UpdateEdgeEvidenceLegacyRequest,
)

router = APIRouter(prefix="/api")


def _graph_response(entities: list, relationships: list) -> dict:
    return {
        "success": True,
        "graph": build_graph_data(entities, relationships),
        "entity_count": len(entities),
        "relationship_count": len(relationships),
    }


@router.get("/graph")
async def get_graph(
    project_id: int = Query(...),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_project(project_id, db)
    gs = load_graph(project_id, db)
    graph_data = build_graph_data(gs["entities"], gs["relationships"])
    return JSONResponse({
        "graph": graph_data,
        "entity_count": len(gs["entities"]),
        "relationship_count": len(gs["relationships"]),
    })


@router.post("/reset")
async def reset_graph(
    body: ProjectIdRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_project(body.project_id, db)
    gs = load_graph(body.project_id, db)
    push_undo(body.project_id, gs["entities"], gs["relationships"])
    save_graph(body.project_id, [], [], [], db)
    log_action("reset_graph", user=user.get("username", ""), details={"project_id": body.project_id})
    return JSONResponse({"success": True})


@router.post("/node/create")
async def create_node(
    body: CreateNodeRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_project(body.project_id, db)
    gs = load_graph(body.project_id, db)
    push_undo(body.project_id, gs["entities"], gs["relationships"])
    new_id = f"manual_{uuid.uuid4().hex[:8]}"
    gs["entities"].append({
        "id": new_id,
        "name": body.name,
        "type": body.type,
        "properties": body.properties,
        "evidence": "Manually created",
        "confidence": "medium",
        "source": "manual",
    })
    save_graph(body.project_id, gs["entities"], gs["relationships"], gs["errors"], db)
    log_action("create_node", user=user.get("username", ""),
               details={"id": new_id, "name": body.name, "type": body.type})
    return JSONResponse(_graph_response(gs["entities"], gs["relationships"]))


@router.post("/node/delete")
async def delete_node(
    body: DeleteNodeRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_project(body.project_id, db)
    gs = load_graph(body.project_id, db)
    entity_ids = {e["id"] for e in gs["entities"]}
    if body.node_id not in entity_ids:
        return JSONResponse({"success": False, "error": "Entity not found"}, status_code=404)
    deleted_name = next((e["name"] for e in gs["entities"] if e["id"] == body.node_id), "")
    push_undo(body.project_id, gs["entities"], gs["relationships"])
    gs["entities"] = [e for e in gs["entities"] if e["id"] != body.node_id]
    gs["relationships"] = [
        r for r in gs["relationships"]
        if r["from_id"] != body.node_id and r["to_id"] != body.node_id
    ]
    save_graph(body.project_id, gs["entities"], gs["relationships"], gs["errors"], db)
    log_action("delete_node", user=user.get("username", ""),
               details={"node_id": body.node_id, "name": deleted_name})
    return JSONResponse(_graph_response(gs["entities"], gs["relationships"]))


@router.post("/connection/create")
async def create_connection(
    body: CreateConnectionRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_project(body.project_id, db)
    gs = load_graph(body.project_id, db)
    entity_ids = {e["id"] for e in gs["entities"]}
    if body.from_id not in entity_ids or body.to_id not in entity_ids:
        return JSONResponse({"success": False, "error": "Invalid entity IDs"}, status_code=400)
    push_undo(body.project_id, gs["entities"], gs["relationships"])
    label = body.label or body.type
    gs["relationships"].append({
        "from_id": body.from_id,
        "to_id": body.to_id,
        "type": body.type,
        "label": label,
        "evidence": "Manually created",
        "confidence": "medium",
        "source": "manual",
    })
    save_graph(body.project_id, gs["entities"], gs["relationships"], gs["errors"], db)
    log_action("create_connection", user=user.get("username", ""),
               details={"from": body.from_id, "to": body.to_id, "type": body.type, "label": label})
    return JSONResponse(_graph_response(gs["entities"], gs["relationships"]))


@router.post("/connection/delete")
async def delete_connection(
    body: DeleteConnectionRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_project(body.project_id, db)
    gs = load_graph(body.project_id, db)
    push_undo(body.project_id, gs["entities"], gs["relationships"])
    idx_str = body.edge_id.replace("edge_", "") if body.edge_id.startswith("edge_") else ""
    deleted_label = ""
    try:
        idx = int(idx_str)
        if 0 <= idx < len(gs["relationships"]):
            deleted_label = gs["relationships"][idx].get("label", "")
            gs["relationships"].pop(idx)
    except (ValueError, IndexError):
        pass
    save_graph(body.project_id, gs["entities"], gs["relationships"], gs["errors"], db)
    log_action("delete_connection", user=user.get("username", ""),
               details={"edge_id": body.edge_id, "label": deleted_label})
    return JSONResponse(_graph_response(gs["entities"], gs["relationships"]))


@router.post("/undo")
async def undo_action(
    body: ProjectIdRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    frame = pop_undo(body.project_id)
    if frame is None:
        return JSONResponse({"success": False, "error": "Nothing to undo"}, status_code=400)
    entities, relationships = frame[0], frame[1]
    rejected_items = frame[2] if len(frame) > 2 else []
    save_graph(body.project_id, entities, relationships, [], db, rejected_items=rejected_items)
    log_action("undo", user=user.get("username", ""))
    return JSONResponse(_graph_response(entities, relationships))


@router.post("/entity/update-evidence")
async def update_entity_evidence_legacy(
    body: UpdateEvidenceLegacyRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Legacy endpoint kept for frontend compatibility."""
    update_body = UpdateEntityRequest(
        project_id=body.project_id,
        entity_id=body.entity_id,
        fields={"evidence": body.evidence},
    )
    return await _do_update_entity(update_body, user, db)


@router.post("/entity/update")
async def update_entity(
    body: UpdateEntityRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await _do_update_entity(body, user, db)


async def _do_update_entity(
    body: UpdateEntityRequest,
    user: dict,
    db: Session,
) -> JSONResponse:
    require_project(body.project_id, db)
    gs = load_graph(body.project_id, db)
    rejected = gs.get("rejected_items", [])
    push_undo(body.project_id, gs["entities"], gs["relationships"], rejected)
    for e in gs["entities"]:
        if e["id"] == body.entity_id:
            if "name" in body.fields:
                e["name"] = body.fields["name"]
            if "type" in body.fields:
                e["type"] = body.fields["type"]
            if "evidence" in body.fields:
                e["evidence"] = body.fields["evidence"]
                if "all_evidence" in e:
                    e["all_evidence"] = [body.fields["evidence"]]
            if "properties" in body.fields:
                e["properties"] = body.fields["properties"]
            break
    save_graph(body.project_id, gs["entities"], gs["relationships"], gs["errors"], db,
               rejected_items=rejected)
    log_action("edit_entity", user=user.get("username", ""),
               details={"entity_id": body.entity_id, "fields_changed": list(body.fields.keys())})
    return JSONResponse(_graph_response(gs["entities"], gs["relationships"]))


@router.post("/edge/update-evidence")
async def update_edge_evidence_legacy(
    body: UpdateEdgeEvidenceLegacyRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Legacy endpoint kept for frontend compatibility."""
    update_body = UpdateEdgeRequest(
        project_id=body.project_id,
        edge_index=body.edge_index,
        edge_id=body.edge_id,
        fields={"evidence": body.evidence},
    )
    return await _do_update_edge(update_body, user, db)


@router.post("/edge/update")
async def update_edge(
    body: UpdateEdgeRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return await _do_update_edge(body, user, db)


async def _do_update_edge(
    body: UpdateEdgeRequest,
    user: dict,
    db: Session,
) -> JSONResponse:
    require_project(body.project_id, db)
    gs = load_graph(body.project_id, db)
    rejected = gs.get("rejected_items", [])
    push_undo(body.project_id, gs["entities"], gs["relationships"], rejected)
    target = None
    if body.edge_index is not None and 0 <= body.edge_index < len(gs["relationships"]):
        target = gs["relationships"][body.edge_index]
    else:
        for r in gs["relationships"]:
            if r.get("id") == body.edge_id or \
               f"{r.get('from_id')}_{r.get('to_id')}_{r.get('type')}" == body.edge_id:
                target = r
                break
    if target:
        if "label" in body.fields:
            target["label"] = body.fields["label"]
        if "type" in body.fields:
            target["type"] = body.fields["type"]
        if "evidence" in body.fields:
            target["evidence"] = body.fields["evidence"]
    save_graph(body.project_id, gs["entities"], gs["relationships"], gs["errors"], db,
               rejected_items=rejected)
    log_action("edit_connection", user=user.get("username", ""),
               details={"edge_index": body.edge_index, "fields_changed": list(body.fields.keys())})
    return JSONResponse(_graph_response(gs["entities"], gs["relationships"]))
