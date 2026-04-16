"""Project service: CRUD operations for investigation projects."""

import json

from sqlalchemy.orm import Session

from app.models import User, Project, GraphSnapshot, DocumentRecord
from app.core.graph_builder import build_graph_data
from app.core.graph_state import load_graph, save_graph, require_project, clear_project_state


def list_projects(db: Session) -> list[dict]:
    """List all projects with entity/relationship counts."""
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
    return result


def create_project(name: str, description: str, user_id: int, db: Session) -> dict:
    """Create a new project with an empty graph snapshot."""
    project = Project(name=name, description=description, created_by=user_id)
    db.add(project)
    db.commit()
    db.refresh(project)
    snap = GraphSnapshot(project_id=project.id)
    db.add(snap)
    db.commit()
    return {"id": project.id, "name": project.name}


def delete_project(project_id: int, db: Session) -> dict:
    """Delete a project and all its associated data."""
    project = require_project(project_id, db)
    db.query(DocumentRecord).filter(DocumentRecord.project_id == project_id).delete()
    db.query(GraphSnapshot).filter(GraphSnapshot.project_id == project_id).delete()
    db.delete(project)
    db.commit()
    clear_project_state(project_id)
    return {"success": True}


def get_project(project_id: int, db: Session) -> dict:
    """Get full project details including graph data."""
    project = require_project(project_id, db)
    gs = load_graph(project_id, db)
    graph_data = build_graph_data(gs.entities, gs.relationships)
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description or "",
        "graph": graph_data,
        "entity_count": len(gs.entities),
        "relationship_count": len(gs.relationships),
        "errors": gs.errors,
        "positions": gs.positions,
    }


def save_positions(project_id: int, positions: dict, db: Session) -> dict:
    """Save node positions for a project's graph layout."""
    require_project(project_id, db)
    gs = load_graph(project_id, db)
    save_graph(
        project_id,
        gs.entities,
        gs.relationships,
        gs.errors,
        db,
        positions=positions,
        rejected_items=gs.rejected_items,
    )
    return {"success": True}
