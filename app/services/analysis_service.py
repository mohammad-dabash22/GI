"""Analysis service: path-finding and AI chat over the graph."""

from sqlalchemy.orm import Session

from app.core.pathfinder import find_shortest_path, find_all_paths
from app.core.graph_state import load_graph, require_project
from app.ai.client import call_llm
from app.services.audit_service import log_action


def find_path(project_id: int, from_id: str, to_id: str,
              max_depth: int, username: str, db: Session) -> dict:
    """Find the shortest path between two nodes."""
    require_project(project_id, db)
    gs = load_graph(project_id, db)
    result = find_shortest_path(gs.entities, gs.relationships, from_id, to_id, max_depth)
    log_action("find_path", user=username,
               details={"from": from_id, "to": to_id, "found": result.get("found", False)})
    return result


def find_all(project_id: int, from_id: str, to_id: str,
             max_depth: int, username: str, db: Session) -> dict:
    """Find all paths between two nodes."""
    require_project(project_id, db)
    gs = load_graph(project_id, db)
    results = find_all_paths(
        gs.entities, gs.relationships,
        from_id, to_id, max_depth, max_paths=10,
    )
    return {"paths": results}


def ai_chat(project_id: int, question: str, username: str, db: Session) -> dict:
    """Answer a natural-language question about the graph using AI."""
    if not question:
        return {"error": "No question provided", "status_code": 400}

    require_project(project_id, db)
    gs = load_graph(project_id, db)

    entities_summary = [
        f"- {e['name']} (type={e.get('type')}, confidence={e.get('confidence')}, "
        f"props={', '.join(f'{k}={v}' for k, v in e.get('properties', {}).items())})"
        for e in gs.entities
    ]
    eid_name = {e["id"]: e["name"] for e in gs.entities}
    rels_summary = [
        f"- {eid_name.get(r['from_id'], r['from_id'])} --[{r.get('type')}]--> "
        f"{eid_name.get(r['to_id'], r['to_id'])} "
        f"(label={r.get('label')}, confidence={r.get('confidence')})"
        for r in gs.relationships
    ]

    graph_ctx = (
        f"ENTITIES ({len(gs.entities)}):\n" + "\n".join(entities_summary[:100]) +
        f"\n\nRELATIONSHIPS ({len(gs.relationships)}):\n" + "\n".join(rels_summary[:100])
    )

    system = (
        "You are a forensic intelligence analyst assistant. The user has a graph of entities and relationships "
        "extracted from investigation documents. Answer their questions about the graph concisely. "
        "If they ask to filter or find specific things, describe what matches. "
        "If they ask about paths or connections, trace the relationships. "
        "Be precise and cite entity names. Keep answers under 200 words unless the user asks for detail. "
        "NEVER include internal entity IDs in your response. Reference entities by their name only."
    )
    user_msg = f"CURRENT GRAPH:\n{graph_ctx}\n\nQUESTION: {question}"

    try:
        answer = call_llm(system, user_msg, max_tokens=1024)
        log_action("ai_chat", user=username, details={"question": question[:100]})
        return {"answer": answer}
    except Exception as e:
        return {"error": str(e), "status_code": 500}
