"""Graph service: all graph mutation operations.

This is the main DRY improvement — the load → undo → mutate → save → respond
pattern that was duplicated across ~10 router endpoints is now written once
in _with_graph_mutation().
"""

import uuid
from typing import Callable

from sqlalchemy.orm import Session

from app.core.graph_builder import build_graph_data
from app.core.graph_state import (
    load_graph, save_graph, push_undo, pop_undo, require_project,
)
from app.domain.graph import GraphState
from app.services.audit_service import log_action


def build_graph_response(entities: list, relationships: list) -> dict:
    """Build a standard graph API response. Single shared implementation."""
    return {
        "success": True,
        "graph": build_graph_data(entities, relationships),
        "entity_count": len(entities),
        "relationship_count": len(relationships),
    }


def _with_graph_mutation(
    project_id: int,
    db: Session,
    mutation: Callable[[GraphState], None],
    *,
    include_rejected: bool = False,
) -> dict:
    """Execute a graph mutation with undo support.

    This consolidates the pattern that was copy-pasted across every endpoint:
    require_project → load_graph → push_undo → mutate → save_graph → respond
    """
    require_project(project_id, db)
    gs = load_graph(project_id, db)
    rejected = gs.rejected_items if include_rejected else []
    push_undo(project_id, gs.entities, gs.relationships, rejected)

    mutation(gs)

    save_graph(
        project_id, gs.entities, gs.relationships, gs.errors, db,
        rejected_items=rejected if include_rejected else None,
    )
    return build_graph_response(gs.entities, gs.relationships)


# ── Public API ───────────────────────────────────────────────────────────────


def get_graph(project_id: int, db: Session) -> dict:
    """Load and return the current graph for a project."""
    require_project(project_id, db)
    gs = load_graph(project_id, db)
    return {
        "graph": build_graph_data(gs.entities, gs.relationships),
        "entity_count": len(gs.entities),
        "relationship_count": len(gs.relationships),
    }


def reset(project_id: int, username: str, db: Session) -> dict:
    """Clear all graph data for a project."""
    def _reset(gs: GraphState):
        gs.entities.clear()
        gs.relationships.clear()
        gs.errors.clear()

    result = _with_graph_mutation(project_id, db, _reset)
    log_action("reset_graph", user=username, details={"project_id": project_id})
    return result


def create_node(project_id: int, name: str, node_type: str,
                properties: dict, username: str, db: Session) -> dict:
    """Create a new manual node in the graph."""
    new_id = f"manual_{uuid.uuid4().hex[:8]}"

    def _create(gs: GraphState):
        gs.entities.append({
            "id": new_id,
            "name": name,
            "type": node_type,
            "properties": properties,
            "evidence": "Manually created",
            "confidence": "medium",
            "source": "manual",
        })

    result = _with_graph_mutation(project_id, db, _create)
    log_action("create_node", user=username,
               details={"id": new_id, "name": name, "type": node_type})
    return result


def delete_node(project_id: int, node_id: str, username: str, db: Session) -> dict:
    """Delete a node and its connected edges."""
    deleted_name = ""

    def _delete(gs: GraphState):
        nonlocal deleted_name
        entity_ids = {e["id"] for e in gs.entities}
        if node_id not in entity_ids:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Entity not found")
        deleted_name = next((e["name"] for e in gs.entities if e["id"] == node_id), "")
        gs.entities[:] = [e for e in gs.entities if e["id"] != node_id]
        gs.relationships[:] = [
            r for r in gs.relationships
            if r["from_id"] != node_id and r["to_id"] != node_id
        ]

    result = _with_graph_mutation(project_id, db, _delete)
    log_action("delete_node", user=username,
               details={"node_id": node_id, "name": deleted_name})
    return result


def create_connection(project_id: int, from_id: str, to_id: str,
                      rel_type: str, label: str, username: str, db: Session) -> dict:
    """Create a new manual connection between two entities."""
    def _create(gs: GraphState):
        entity_ids = {e["id"] for e in gs.entities}
        if from_id not in entity_ids or to_id not in entity_ids:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Invalid entity IDs")
        gs.relationships.append({
            "from_id": from_id,
            "to_id": to_id,
            "type": rel_type,
            "label": label or rel_type,
            "evidence": "Manually created",
            "confidence": "medium",
            "source": "manual",
        })

    result = _with_graph_mutation(project_id, db, _create)
    log_action("create_connection", user=username,
               details={"from": from_id, "to": to_id, "type": rel_type, "label": label or rel_type})
    return result


def delete_connection(project_id: int, edge_id: str, username: str, db: Session) -> dict:
    """Delete a connection by edge ID."""
    deleted_label = ""

    def _delete(gs: GraphState):
        nonlocal deleted_label
        idx_str = edge_id.replace("edge_", "") if edge_id.startswith("edge_") else ""
        try:
            idx = int(idx_str)
            if 0 <= idx < len(gs.relationships):
                deleted_label = gs.relationships[idx].get("label", "")
                gs.relationships.pop(idx)
        except (ValueError, IndexError):
            pass

    result = _with_graph_mutation(project_id, db, _delete)
    log_action("delete_connection", user=username,
               details={"edge_id": edge_id, "label": deleted_label})
    return result


def undo(project_id: int, username: str, db: Session) -> dict:
    """Undo the last graph mutation."""
    frame = pop_undo(project_id)
    if frame is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Nothing to undo")
    entities, relationships = frame[0], frame[1]
    rejected_items = frame[2] if len(frame) > 2 else []
    save_graph(project_id, entities, relationships, [], db, rejected_items=rejected_items)
    log_action("undo", user=username)
    return build_graph_response(entities, relationships)


def update_entity(project_id: int, entity_id: str, fields: dict,
                  username: str, db: Session) -> dict:
    """Update fields on an existing entity."""
    def _update(gs: GraphState):
        for e in gs.entities:
            if e["id"] == entity_id:
                if "name" in fields:
                    e["name"] = fields["name"]
                if "type" in fields:
                    e["type"] = fields["type"]
                if "evidence" in fields:
                    e["evidence"] = fields["evidence"]
                    if "all_evidence" in e:
                        e["all_evidence"] = [fields["evidence"]]
                if "properties" in fields:
                    e["properties"] = fields["properties"]
                break

    result = _with_graph_mutation(project_id, db, _update, include_rejected=True)
    log_action("edit_entity", user=username,
               details={"entity_id": entity_id, "fields_changed": list(fields.keys())})
    return result


def update_edge(project_id: int, edge_index: int | None, edge_id: str,
                fields: dict, username: str, db: Session) -> dict:
    """Update fields on an existing edge."""
    def _update(gs: GraphState):
        target = None
        if edge_index is not None and 0 <= edge_index < len(gs.relationships):
            target = gs.relationships[edge_index]
        else:
            for r in gs.relationships:
                if r.get("id") == edge_id or \
                   f"{r.get('from_id')}_{r.get('to_id')}_{r.get('type')}" == edge_id:
                    target = r
                    break
        if target:
            if "label" in fields:
                target["label"] = fields["label"]
            if "type" in fields:
                target["type"] = fields["type"]
            if "evidence" in fields:
                target["evidence"] = fields["evidence"]

    result = _with_graph_mutation(project_id, db, _update, include_rejected=True)
    log_action("edit_connection", user=username,
               details={"edge_index": edge_index, "fields_changed": list(fields.keys())})
    return result
