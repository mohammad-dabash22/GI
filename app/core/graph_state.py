"""In-memory state helpers for graph operations: undo stack, pipeline status.

DB persistence for the graph itself is handled via load_graph / save_graph,
which convert between the typed GraphState and the GraphSnapshot ORM model.
"""

import copy
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.domain.graph import GraphState
from app.models import GraphSnapshot, Project

MAX_UNDO = 50

_undo_stacks: dict[int, list] = {}
_pipeline_statuses: dict[int, dict] = {}


def load_graph(project_id: int, db: Session) -> GraphState:
    """Load a project's graph from the database into a typed GraphState."""
    snap = db.query(GraphSnapshot).filter(GraphSnapshot.project_id == project_id).first()
    if snap:
        return GraphState(
            entities=json.loads(snap.entities or "[]"),
            relationships=json.loads(snap.relationships or "[]"),
            errors=json.loads(snap.errors or "[]"),
            positions=json.loads(snap.node_positions or "{}"),
            rejected_items=json.loads(snap.rejected_items or "[]"),
        )
    return GraphState()


def save_graph(
    project_id: int,
    entities: list,
    relationships: list,
    errors: list,
    db: Session,
    positions: dict = None,
    rejected_items: list = None,
):
    """Persist graph data to the database."""
    snap = db.query(GraphSnapshot).filter(GraphSnapshot.project_id == project_id).first()
    if not snap:
        snap = GraphSnapshot(project_id=project_id)
        db.add(snap)
    snap.entities = json.dumps(entities)
    snap.relationships = json.dumps(relationships)
    snap.errors = json.dumps(errors)
    if positions is not None:
        snap.node_positions = json.dumps(positions)
    if rejected_items is not None:
        snap.rejected_items = json.dumps(rejected_items)
    project = db.query(Project).filter(Project.id == project_id).first()
    if project:
        project.updated_at = datetime.now(timezone.utc)
    db.commit()


def push_undo(project_id: int, entities: list, relationships: list, rejected_items: list = None):
    """Push current state onto the undo stack for a project."""
    stack = _undo_stacks.setdefault(project_id, [])
    stack.append((
        copy.deepcopy(entities),
        copy.deepcopy(relationships),
        copy.deepcopy(rejected_items or []),
    ))
    if len(stack) > MAX_UNDO:
        stack.pop(0)


def pop_undo(project_id: int) -> tuple | None:
    """Pop the most recent undo frame, or None if empty."""
    stack = _undo_stacks.get(project_id, [])
    return stack.pop() if stack else None


def clear_project_state(project_id: int):
    """Remove all in-memory state for a deleted project."""
    _undo_stacks.pop(project_id, None)
    _pipeline_statuses.pop(project_id, None)


def get_pipeline_status(project_id: int) -> dict:
    """Get or create a pipeline status tracker for a project."""
    return _pipeline_statuses.setdefault(project_id, {
        "running": False,
        "current_pass": 0,
        "pass_detail": "",
        "events": [],
    })


def require_project(project_id: int, db: Session) -> Project:
    """Validate that a project exists, or raise 404."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
