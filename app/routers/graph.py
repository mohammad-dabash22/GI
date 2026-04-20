"""Graph mutation routes — thin controller delegating to graph_service.

Compare with the old routers/graph.py (292 lines of mixed logic).
Each endpoint is now 3-5 lines: parse request → call service → return response.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.models import get_db
from app.services.auth_service import get_current_user
from app.services import graph_service
from app.schemas.graph import (
    ProjectIdRequest, CreateNodeRequest, DeleteNodeRequest,
    CreateConnectionRequest, DeleteConnectionRequest, MergeNodesRequest,
    UpdateEntityRequest, UpdateEdgeRequest,
    UpdateEvidenceLegacyRequest, UpdateEdgeEvidenceLegacyRequest,
)

router = APIRouter(prefix="/api")


@router.get("/graph")
async def get_graph(
    project_id: int = Query(...),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(graph_service.get_graph(project_id, db))


@router.post("/reset")
async def reset_graph(
    body: ProjectIdRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(graph_service.reset(body.project_id, user.get("username", ""), db))


@router.post("/node/create")
async def create_node(
    body: CreateNodeRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(graph_service.create_node(
        body.project_id, body.name, body.type, body.properties,
        user.get("username", ""), db
    ))


@router.post("/node/delete")
async def delete_node(
    body: DeleteNodeRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(graph_service.delete_node(
        body.project_id, body.node_id, user.get("username", ""), db
    ))


@router.post("/connection/create")
async def create_connection(
    body: CreateConnectionRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(graph_service.create_connection(
        body.project_id, body.from_id, body.to_id, body.type, body.label,
        user.get("username", ""), db
    ))


@router.post("/connection/delete")
async def delete_connection(
    body: DeleteConnectionRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(graph_service.delete_connection(
        body.project_id, body.edge_id, user.get("username", ""), db
    ))


@router.post("/graph/merge")
async def merge_nodes(
    body: MergeNodesRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(graph_service.merge_nodes(
        body.project_id, body.target_id, body.source_id,
        user.get("username", ""), db
    ))


@router.post("/undo")
async def undo_action(
    body: ProjectIdRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(graph_service.undo(body.project_id, user.get("username", ""), db))


@router.post("/entity/update-evidence")
async def update_entity_evidence_legacy(
    body: UpdateEvidenceLegacyRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Legacy endpoint kept for frontend compatibility."""
    return JSONResponse(graph_service.update_entity(
        body.project_id, body.entity_id, {"evidence": body.evidence},
        user.get("username", ""), db
    ))


@router.post("/entity/update")
async def update_entity(
    body: UpdateEntityRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(graph_service.update_entity(
        body.project_id, body.entity_id, body.fields,
        user.get("username", ""), db
    ))


@router.post("/edge/update-evidence")
async def update_edge_evidence_legacy(
    body: UpdateEdgeEvidenceLegacyRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Legacy endpoint kept for frontend compatibility."""
    return JSONResponse(graph_service.update_edge(
        body.project_id, body.edge_index, body.edge_id, {"evidence": body.evidence},
        user.get("username", ""), db
    ))


@router.post("/edge/update")
async def update_edge(
    body: UpdateEdgeRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(graph_service.update_edge(
        body.project_id, body.edge_index, body.edge_id, body.fields,
        user.get("username", ""), db
    ))
