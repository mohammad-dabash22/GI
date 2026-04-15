from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_user
from audit_log import log_action
from pathfinder import find_shortest_path, find_all_paths
from graph_state import load_graph, require_project
from schemas.graph import FindPathRequest, FindAllPathsRequest, ChatRequest

router = APIRouter(prefix="/api")


@router.post("/path/find")
async def find_path(
    body: FindPathRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_project(body.project_id, db)
    gs = load_graph(body.project_id, db)
    result = find_shortest_path(gs["entities"], gs["relationships"], body.from_id, body.to_id, body.max_depth)
    log_action("find_path", user=user.get("username", ""),
               details={"from": body.from_id, "to": body.to_id, "found": result.get("found", False)})
    return JSONResponse(result)


@router.post("/path/all")
async def find_all(
    body: FindAllPathsRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_project(body.project_id, db)
    gs = load_graph(body.project_id, db)
    results = find_all_paths(
        gs["entities"], gs["relationships"],
        body.from_id, body.to_id, body.max_depth, max_paths=10,
    )
    return JSONResponse({"paths": results})


@router.post("/chat")
async def ai_chat(
    body: ChatRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not body.question:
        return JSONResponse({"error": "No question provided"}, status_code=400)

    require_project(body.project_id, db)
    gs = load_graph(body.project_id, db)

    entities_summary = [
        f"- {e['name']} (type={e.get('type')}, confidence={e.get('confidence')}, "
        f"props={', '.join(f'{k}={v}' for k, v in e.get('properties', {}).items())})"
        for e in gs["entities"]
    ]
    eid_name = {e["id"]: e["name"] for e in gs["entities"]}
    rels_summary = [
        f"- {eid_name.get(r['from_id'], r['from_id'])} --[{r.get('type')}]--> "
        f"{eid_name.get(r['to_id'], r['to_id'])} "
        f"(label={r.get('label')}, confidence={r.get('confidence')})"
        for r in gs["relationships"]
    ]

    graph_ctx = (
        f"ENTITIES ({len(gs['entities'])}):\n" + "\n".join(entities_summary[:100]) +
        f"\n\nRELATIONSHIPS ({len(gs['relationships'])}):\n" + "\n".join(rels_summary[:100])
    )

    system = (
        "You are a forensic intelligence analyst assistant. The user has a graph of entities and relationships "
        "extracted from investigation documents. Answer their questions about the graph concisely. "
        "If they ask to filter or find specific things, describe what matches. "
        "If they ask about paths or connections, trace the relationships. "
        "Be precise and cite entity names. Keep answers under 200 words unless the user asks for detail. "
        "NEVER include internal entity IDs in your response. Reference entities by their name only."
    )
    user_msg = f"CURRENT GRAPH:\n{graph_ctx}\n\nQUESTION: {body.question}"

    try:
        from ai_extraction import _call_llm
        answer = _call_llm(system, user_msg, max_tokens=1024)
        log_action("ai_chat", user=user.get("username", ""), details={"question": body.question[:100]})
        return JSONResponse({"answer": answer})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
