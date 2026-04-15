import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from models import User, Project, GraphSnapshot, DocumentRecord
from auth import get_current_user
from graph_state import load_graph, require_project, clear_project_state, save_graph
from graph_builder import build_graph_data
from schemas.projects import CreateProjectRequest, SavePositionsRequest

router = APIRouter(prefix="/api")


@router.get("/projects")
async def list_projects(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    projects = db.query(Project).order_by(Project.updated_at.desc()).all()
    result = []
    for p in projects:
        snap = db.query(GraphSnapshot).filter(GraphSnapshot.project_id == p.id).first()
        ent_count = len(json.loads(snap.entities)) if snap and snap.entities else 0
        rel_count = len(json.loads(snap.relationships)) if snap and snap.relationships else 0
        creator = db.query(User).filter(User.id == p.created_by).first()
        result.append({
            "id": p.id,
            "name": p.name,
            "description": p.description or "",
            "created_by": p.created_by,
            "created_by_name": creator.username if creator else "?",
            "created_at": p.created_at.isoformat() if p.created_at else "",
            "updated_at": p.updated_at.isoformat() if p.updated_at else "",
            "entity_count": ent_count,
            "relationship_count": rel_count,
        })
    return JSONResponse({"projects": result})


@router.post("/projects")
async def create_project(
    body: CreateProjectRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = Project(name=body.name, description=body.description, created_by=user["sub"])
    db.add(project)
    db.commit()
    db.refresh(project)
    snap = GraphSnapshot(project_id=project.id)
    db.add(snap)
    db.commit()
    return JSONResponse({"id": project.id, "name": project.name})


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = require_project(project_id, db)
    db.query(DocumentRecord).filter(DocumentRecord.project_id == project_id).delete()
    db.query(GraphSnapshot).filter(GraphSnapshot.project_id == project_id).delete()
    db.delete(project)
    db.commit()
    clear_project_state(project_id)
    return JSONResponse({"success": True})


@router.get("/projects/{project_id}")
async def get_project(
    project_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = require_project(project_id, db)
    gs = load_graph(project_id, db)
    graph_data = build_graph_data(gs["entities"], gs["relationships"])
    return JSONResponse({
        "id": project.id,
        "name": project.name,
        "description": project.description or "",
        "graph": graph_data,
        "entity_count": len(gs["entities"]),
        "relationship_count": len(gs["relationships"]),
        "errors": gs["errors"],
        "positions": gs.get("positions", {}),
    })


@router.post("/graph/positions")
async def save_positions(
    body: SavePositionsRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_project(body.project_id, db)
    gs = load_graph(body.project_id, db)
    save_graph(
        body.project_id,
        gs["entities"],
        gs["relationships"],
        gs["errors"],
        db,
        positions=body.positions,
        rejected_items=gs.get("rejected_items"),
    )
    return JSONResponse({"success": True})
