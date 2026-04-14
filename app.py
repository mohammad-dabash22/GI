import os
import json
import uuid
import copy
from datetime import datetime
from fastapi import FastAPI, UploadFile, File, Form, Request, Depends, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from config import UPLOAD_DIR, ALLOWED_EXTENSIONS, DOCUMENT_TYPES
from extractors import extract_text
from ai_extraction import extract_full_pipeline, extract_from_document
from deduplication import deduplicate_entities, remap_relationships
from graph_builder import build_graph_data
from audit_log import log_action, get_log, clear_log
from pathfinder import find_shortest_path, find_all_paths
from database import get_db, init_db, SessionLocal
from models import User, Project, GraphSnapshot, DocumentRecord
from auth import (
    hash_password, verify_password, create_token,
    get_current_user, get_current_user_or_token,
)

app = FastAPI(title="Forensic Graph PoC")


@app.on_event("startup")
def on_startup():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    init_db()
    _seed_test_project()


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

MAX_UNDO = 50
_undo_stacks: dict[int, list] = {}
_pipeline_statuses: dict[int, dict] = {}


# ═══════════════════════════════════════════════════════════════
# DB HELPERS
# ═══════════════════════════════════════════════════════════════

def _load_graph(project_id: int, db: Session) -> dict:
    snap = db.query(GraphSnapshot).filter(GraphSnapshot.project_id == project_id).first()
    if snap:
        return {
            "entities": json.loads(snap.entities or "[]"),
            "relationships": json.loads(snap.relationships or "[]"),
            "errors": json.loads(snap.errors or "[]"),
            "positions": json.loads(snap.node_positions or "{}"),
            "rejected_items": json.loads(snap.rejected_items or "[]"),
        }
    return {"entities": [], "relationships": [], "errors": [], "positions": {}, "rejected_items": []}


def _save_graph(project_id: int, entities: list, relationships: list,
                errors: list, db: Session, positions: dict = None,
                rejected_items: list = None):
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
        from datetime import timezone
        project.updated_at = datetime.now(timezone.utc)
    db.commit()


def _push_undo(project_id: int, entities: list, relationships: list,
               rejected_items: list = None):
    stack = _undo_stacks.setdefault(project_id, [])
    stack.append((copy.deepcopy(entities), copy.deepcopy(relationships),
                  copy.deepcopy(rejected_items or [])))
    if len(stack) > MAX_UNDO:
        stack.pop(0)


def _get_pipeline_status(project_id: int) -> dict:
    return _pipeline_statuses.setdefault(project_id, {
        "running": False, "current_pass": 0, "pass_detail": "", "events": [],
    })


def _require_project(project_id: int, db: Session) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


# ═══════════════════════════════════════════════════════════════
# AUTH ROUTES (no token required)
# ═══════════════════════════════════════════════════════════════

@app.post("/api/auth/register")
async def register(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")
    if not username or len(username) < 2:
        raise HTTPException(400, "Username must be at least 2 characters")
    if not password or len(password) < 4:
        raise HTTPException(400, "Password must be at least 4 characters")
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(409, "Username already taken")
    user = User(username=username, password_hash=hash_password(password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return JSONResponse({"id": user.id, "username": user.username})


@app.post("/api/auth/login")
async def login(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    token = create_token(user.id, user.username)
    return JSONResponse({"token": token, "username": user.username, "user_id": user.id})


# ═══════════════════════════════════════════════════════════════
# PROJECT ROUTES
# ═══════════════════════════════════════════════════════════════

@app.get("/api/projects")
async def list_projects(user: dict = Depends(get_current_user),
                        db: Session = Depends(get_db)):
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


@app.post("/api/projects")
async def create_project(request: Request,
                         user: dict = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "Project name is required")
    project = Project(name=name, description=body.get("description", ""),
                      created_by=user["sub"])
    db.add(project)
    db.commit()
    db.refresh(project)
    snap = GraphSnapshot(project_id=project.id)
    db.add(snap)
    db.commit()
    return JSONResponse({"id": project.id, "name": project.name})


@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: int,
                         user: dict = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    project = _require_project(project_id, db)
    db.query(DocumentRecord).filter(DocumentRecord.project_id == project_id).delete()
    db.query(GraphSnapshot).filter(GraphSnapshot.project_id == project_id).delete()
    db.delete(project)
    db.commit()
    _undo_stacks.pop(project_id, None)
    _pipeline_statuses.pop(project_id, None)
    return JSONResponse({"success": True})


@app.get("/api/projects/{project_id}")
async def get_project(project_id: int,
                      user: dict = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    project = _require_project(project_id, db)
    gs = _load_graph(project_id, db)
    graph_data = build_graph_data(gs["entities"], gs["relationships"])
    return JSONResponse({
        "id": project.id,
        "name": project.name,
        "description": project.description or "",
        "graph": graph_data,
        "entity_count": len(gs["entities"]),
        "relationship_count": len(gs["relationships"]),
        "errors": gs["errors"],
        "positions": gs["positions"],
    })


@app.post("/api/graph/positions")
async def save_positions(request: Request,
                         user: dict = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    body = await request.json()
    project_id = body.get("project_id")
    positions = body.get("positions", {})
    waypoints = body.get("waypoints", None)
    if not project_id:
        raise HTTPException(400, "project_id required")
    _require_project(project_id, db)
    snap = db.query(GraphSnapshot).filter(GraphSnapshot.project_id == project_id).first()
    if snap:
        pos_data = positions
        if waypoints is not None:
            pos_data["_waypoints"] = waypoints
        snap.node_positions = json.dumps(pos_data)
        db.commit()
    return JSONResponse({"success": True})


# ═══════════════════════════════════════════════════════════════
# PAGE ROUTES
# ═══════════════════════════════════════════════════════════════

@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/projects")
async def projects_page(request: Request):
    return templates.TemplateResponse("projects.html", {"request": request})


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ═══════════════════════════════════════════════════════════════
# EXISTING API ROUTES (now auth + project-scoped)
# ═══════════════════════════════════════════════════════════════

@app.get("/api/document-types")
async def get_document_types(user: dict = Depends(get_current_user)):
    return JSONResponse({"types": DOCUMENT_TYPES})


@app.post("/api/upload")
async def upload_documents(
    request: Request,
    files: list[UploadFile] = File(...),
    doc_types: str = Form("{}"),
    mode: str = Form("incremental"),
    project_id: int = Form(...),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_project(project_id, db)
    gs = _load_graph(project_id, db)
    _push_undo(project_id, gs["entities"], gs["relationships"])

    if mode == "new":
        gs["entities"] = []
        gs["relationships"] = []
        gs["errors"] = []

    try:
        doc_type_map = json.loads(doc_types)
    except (json.JSONDecodeError, TypeError):
        doc_type_map = {}

    files_data = []
    all_errors = list(gs["errors"])

    for file in files:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            all_errors.append(f"Skipped unsupported file: {file.filename}")
            continue

        safe_name = f"{uuid.uuid4().hex}_{file.filename}"
        save_path = os.path.join(UPLOAD_DIR, safe_name)
        content = await file.read()
        with open(save_path, "wb") as f:
            f.write(content)

        doc_rec = DocumentRecord(
            project_id=project_id,
            original_name=file.filename,
            stored_filename=safe_name,
            doc_type=doc_type_map.get(file.filename, "Other"),
            file_path=save_path,
        )
        db.add(doc_rec)
        db.commit()

        try:
            filename, chunks = extract_text(save_path)
            if not chunks:
                all_errors.append(f"No text extracted from {file.filename}")
                continue
            full_text = "\n\n".join(c["text"] for c in chunks)
            dtype = doc_type_map.get(file.filename, "Other")
            files_data.append({
                "filename": filename, "chunks": chunks,
                "doc_type": dtype, "full_text": full_text,
            })
        except Exception as e:
            all_errors.append(f"Error reading {file.filename}: {str(e)}")

    if not files_data:
        return JSONResponse({"success": False, "error": "No processable files",
                             "errors": all_errors}, status_code=400)

    ps = _get_pipeline_status(project_id)
    ps["running"] = True
    ps["current_pass"] = 0
    ps["pass_detail"] = "Starting..."
    ps["events"] = []

    def _progress_cb(pass_name, current, total):
        ps["current_pass"] = int(pass_name.replace("pass", ""))
        ps["pass_detail"] = f"{pass_name}: {current}/{total}"

    try:
        result = extract_full_pipeline(files_data, progress_cb=_progress_cb)
        new_entities = result["entities"]
        new_relationships = result["relationships"]
        all_errors.extend(result.get("errors", []))

        combined_entities = list(gs["entities"]) + new_entities
        combined_rels = list(gs["relationships"]) + new_relationships
        deduped_entities, id_mapping = deduplicate_entities(combined_entities)
        remapped_rels = remap_relationships(combined_rels, id_mapping)

        _save_graph(project_id, deduped_entities, remapped_rels, all_errors, db)
        graph_data = build_graph_data(deduped_entities, remapped_rels)

        log_action("upload_documents", user=user.get("username", ""), details={
            "project_id": project_id,
            "files": [fd["filename"] for fd in files_data],
            "entities_extracted": len(deduped_entities),
            "relationships_extracted": len(remapped_rels),
            "mode": mode,
        })

        return JSONResponse({
            "success": True,
            "files_processed": [fd["filename"] for fd in files_data],
            "entity_count": len(deduped_entities),
            "relationship_count": len(remapped_rels),
            "errors": all_errors,
            "graph": graph_data,
            "pipeline": {
                "passes_completed": result.get("pass", 0),
                "merges_applied": result.get("pass2_result", {}).get("merges_applied", 0),
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        all_errors.append(f"Pipeline error: {str(e)}")
        return JSONResponse({"success": False, "error": str(e),
                             "errors": all_errors}, status_code=500)
    finally:
        ps["running"] = False


@app.get("/api/pipeline/status")
async def pipeline_status_endpoint(project_id: int = Query(...),
                                   user: dict = Depends(get_current_user)):
    ps = _get_pipeline_status(project_id)
    return JSONResponse({
        "running": ps["running"],
        "current_pass": ps["current_pass"],
        "pass_detail": ps["pass_detail"],
    })


@app.post("/api/reset")
async def reset_graph(request: Request,
                      user: dict = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    body = await request.json()
    project_id = body.get("project_id")
    if not project_id:
        raise HTTPException(400, "project_id required")
    _require_project(project_id, db)
    gs = _load_graph(project_id, db)
    _push_undo(project_id, gs["entities"], gs["relationships"])
    _save_graph(project_id, [], [], [], db)
    log_action("reset_graph", user=user.get("username", ""), details={"project_id": project_id})
    return JSONResponse({"success": True})


@app.get("/api/graph")
async def get_graph(project_id: int = Query(...),
                    user: dict = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    _require_project(project_id, db)
    gs = _load_graph(project_id, db)
    graph_data = build_graph_data(gs["entities"], gs["relationships"])
    return JSONResponse({
        "graph": graph_data,
        "entity_count": len(gs["entities"]),
        "relationship_count": len(gs["relationships"]),
    })


@app.post("/api/connection/delete")
async def delete_connection(request: Request,
                            user: dict = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    body = await request.json()
    project_id = body.get("project_id")
    edge_id = body.get("edge_id", "")
    if not project_id:
        raise HTTPException(400, "project_id required")
    _require_project(project_id, db)
    gs = _load_graph(project_id, db)
    _push_undo(project_id, gs["entities"], gs["relationships"])
    idx_str = edge_id.replace("edge_", "") if edge_id.startswith("edge_") else ""
    deleted_label = ""
    try:
        idx = int(idx_str)
        if 0 <= idx < len(gs["relationships"]):
            deleted_label = gs["relationships"][idx].get("label", "")
            gs["relationships"].pop(idx)
    except (ValueError, IndexError):
        pass
    _save_graph(project_id, gs["entities"], gs["relationships"], gs["errors"], db)
    log_action("delete_connection", user=user.get("username", ""),
               details={"edge_id": edge_id, "label": deleted_label})
    graph_data = build_graph_data(gs["entities"], gs["relationships"])
    return JSONResponse({"success": True, "graph": graph_data,
                         "entity_count": len(gs["entities"]),
                         "relationship_count": len(gs["relationships"])})


@app.post("/api/connection/create")
async def create_connection(request: Request,
                            user: dict = Depends(get_current_user),
                            db: Session = Depends(get_db)):
    body = await request.json()
    project_id = body.get("project_id")
    from_id = body.get("from_id")
    to_id = body.get("to_id")
    rel_type = body.get("type", "related_to")
    label = body.get("label", rel_type)
    if not project_id:
        raise HTTPException(400, "project_id required")
    _require_project(project_id, db)
    gs = _load_graph(project_id, db)
    entity_ids = {e["id"] for e in gs["entities"]}
    if from_id not in entity_ids or to_id not in entity_ids:
        return JSONResponse({"success": False, "error": "Invalid entity IDs"}, status_code=400)
    _push_undo(project_id, gs["entities"], gs["relationships"])
    gs["relationships"].append({
        "from_id": from_id, "to_id": to_id, "type": rel_type,
        "label": label, "evidence": "Manually created", "confidence": "medium",
        "source": "manual"
    })
    _save_graph(project_id, gs["entities"], gs["relationships"], gs["errors"], db)
    log_action("create_connection", user=user.get("username", ""),
               details={"from": from_id, "to": to_id, "type": rel_type, "label": label})
    graph_data = build_graph_data(gs["entities"], gs["relationships"])
    return JSONResponse({"success": True, "graph": graph_data,
                         "entity_count": len(gs["entities"]),
                         "relationship_count": len(gs["relationships"])})


@app.post("/api/node/create")
async def create_node(request: Request,
                      user: dict = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    body = await request.json()
    project_id = body.get("project_id")
    name = body.get("name", "").strip()
    ntype = body.get("type", "Person")
    props = body.get("properties", {})
    if not project_id:
        raise HTTPException(400, "project_id required")
    if not name:
        return JSONResponse({"success": False, "error": "Name is required"}, status_code=400)
    _require_project(project_id, db)
    gs = _load_graph(project_id, db)
    _push_undo(project_id, gs["entities"], gs["relationships"])
    new_id = f"manual_{uuid.uuid4().hex[:8]}"
    gs["entities"].append({
        "id": new_id, "name": name, "type": ntype,
        "properties": props, "evidence": "Manually created",
        "confidence": "medium", "source": "manual"
    })
    _save_graph(project_id, gs["entities"], gs["relationships"], gs["errors"], db)
    log_action("create_node", user=user.get("username", ""),
               details={"id": new_id, "name": name, "type": ntype})
    graph_data = build_graph_data(gs["entities"], gs["relationships"])
    return JSONResponse({"success": True, "graph": graph_data,
                         "entity_count": len(gs["entities"]),
                         "relationship_count": len(gs["relationships"])})


@app.post("/api/node/delete")
async def delete_node(request: Request,
                      user: dict = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    body = await request.json()
    project_id = body.get("project_id")
    node_id = body.get("node_id", "")
    if not project_id:
        raise HTTPException(400, "project_id required")
    _require_project(project_id, db)
    gs = _load_graph(project_id, db)
    entity_ids = {e["id"] for e in gs["entities"]}
    if node_id not in entity_ids:
        return JSONResponse({"success": False, "error": "Entity not found"}, status_code=404)
    deleted_name = next((e["name"] for e in gs["entities"] if e["id"] == node_id), "")
    _push_undo(project_id, gs["entities"], gs["relationships"])
    gs["entities"] = [e for e in gs["entities"] if e["id"] != node_id]
    gs["relationships"] = [r for r in gs["relationships"]
                           if r["from_id"] != node_id and r["to_id"] != node_id]
    _save_graph(project_id, gs["entities"], gs["relationships"], gs["errors"], db)
    log_action("delete_node", user=user.get("username", ""),
               details={"node_id": node_id, "name": deleted_name})
    graph_data = build_graph_data(gs["entities"], gs["relationships"])
    return JSONResponse({"success": True, "graph": graph_data,
                         "entity_count": len(gs["entities"]),
                         "relationship_count": len(gs["relationships"])})


@app.post("/api/undo")
async def undo_action(request: Request,
                      user: dict = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    body = await request.json()
    project_id = body.get("project_id")
    if not project_id:
        raise HTTPException(400, "project_id required")
    stack = _undo_stacks.get(project_id, [])
    if not stack:
        return JSONResponse({"success": False, "error": "Nothing to undo"}, status_code=400)
    frame = stack.pop()
    entities, relationships = frame[0], frame[1]
    rejected_items = frame[2] if len(frame) > 2 else []
    _save_graph(project_id, entities, relationships, [], db,
                rejected_items=rejected_items)
    log_action("undo", user=user.get("username", ""))
    graph_data = build_graph_data(entities, relationships)
    return JSONResponse({"success": True, "graph": graph_data,
                         "entity_count": len(entities),
                         "relationship_count": len(relationships)})


@app.post("/api/entity/update-evidence")
async def update_evidence_legacy(request: Request,
                                 user: dict = Depends(get_current_user),
                                 db: Session = Depends(get_db)):
    """Legacy endpoint -- redirects to /api/entity/update"""
    body = await request.json()
    body["fields"] = {"evidence": body.get("evidence", "")}
    request._body = json.dumps(body).encode()
    return await update_entity(request, user, db)


@app.post("/api/entity/update")
async def update_entity(request: Request,
                        user: dict = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    body = await request.json()
    project_id = body.get("project_id")
    entity_id = body.get("entity_id", "")
    fields = body.get("fields", {})
    if not project_id:
        raise HTTPException(400, "project_id required")
    _require_project(project_id, db)
    gs = _load_graph(project_id, db)
    rejected = gs.get("rejected_items", [])
    _push_undo(project_id, gs["entities"], gs["relationships"], rejected)
    for e in gs["entities"]:
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
    _save_graph(project_id, gs["entities"], gs["relationships"], gs["errors"], db,
                rejected_items=rejected)
    log_action("edit_entity", user=user.get("username", ""),
               details={"entity_id": entity_id, "fields_changed": list(fields.keys())})
    graph_data = build_graph_data(gs["entities"], gs["relationships"])
    return JSONResponse({"success": True, "graph": graph_data,
                         "entity_count": len(gs["entities"]),
                         "relationship_count": len(gs["relationships"])})


@app.post("/api/edge/update-evidence")
async def update_edge_evidence_legacy(request: Request,
                                      user: dict = Depends(get_current_user),
                                      db: Session = Depends(get_db)):
    """Legacy endpoint"""
    body = await request.json()
    body["fields"] = {"evidence": body.get("evidence", "")}
    request._body = json.dumps(body).encode()
    return await update_edge(request, user, db)


@app.post("/api/edge/update")
async def update_edge(request: Request,
                      user: dict = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    body = await request.json()
    project_id = body.get("project_id")
    edge_index = body.get("edge_index")
    edge_id = body.get("edge_id", "")
    fields = body.get("fields", {})
    if not project_id:
        raise HTTPException(400, "project_id required")
    _require_project(project_id, db)
    gs = _load_graph(project_id, db)
    rejected = gs.get("rejected_items", [])
    _push_undo(project_id, gs["entities"], gs["relationships"], rejected)
    target = None
    if edge_index is not None and 0 <= edge_index < len(gs["relationships"]):
        target = gs["relationships"][edge_index]
    else:
        for r in gs["relationships"]:
            if r.get("id") == edge_id or f"{r.get('from_id')}_{r.get('to_id')}_{r.get('type')}" == edge_id:
                target = r
                break
    if target:
        if "label" in fields:
            target["label"] = fields["label"]
        if "type" in fields:
            target["type"] = fields["type"]
        if "evidence" in fields:
            target["evidence"] = fields["evidence"]
    _save_graph(project_id, gs["entities"], gs["relationships"], gs["errors"], db,
                rejected_items=rejected)
    log_action("edit_connection", user=user.get("username", ""),
               details={"edge_index": edge_index, "fields_changed": list(fields.keys())})
    graph_data = build_graph_data(gs["entities"], gs["relationships"])
    return JSONResponse({"success": True, "graph": graph_data,
                         "entity_count": len(gs["entities"]),
                         "relationship_count": len(gs["relationships"])})


def _get_demo_data():
    demo_entities = [
        {"id": "p1", "name": "Viktor Petrov", "type": "Person", "properties": {"role": "CEO", "nationality": "Russian"}, "evidence": "Viktor Petrov, CEO of Meridian Holdings", "confidence": "high", "confidence_score": 9, "confidence_reason": "Explicitly named as CEO in investigation report page 1", "source": "investigation_report.pdf:Page 1"},
        {"id": "p2", "name": "Elena Vasquez", "type": "Person", "properties": {"role": "CFO"}, "evidence": "Elena Vasquez served as CFO", "confidence": "high", "confidence_score": 9, "confidence_reason": "Directly stated role in investigation report", "source": "investigation_report.pdf:Page 1"},
        {"id": "p3", "name": "James Thornton", "type": "Person", "properties": {"role": "Nominee Director"}, "evidence": "James Thornton, a nominee director", "confidence": "high", "confidence_score": 8, "confidence_reason": "Named in corporate records as nominee director", "source": "corporate_records.docx:Paragraph 3"},
        {"id": "p4", "name": "Maria Santos", "type": "Person", "properties": {"role": "Accountant"}, "evidence": "accountant Maria Santos who processed wire transfers", "confidence": "medium", "confidence_score": 6, "confidence_reason": "Mentioned in notes but role not confirmed in official records", "source": "notes.txt:Lines 1-50"},
        {"id": "p5", "name": "Ahmed Al-Rashid", "type": "Person", "properties": {"role": "Intermediary"}, "evidence": "intermediary Ahmed Al-Rashid facilitated introductions", "confidence": "medium", "confidence_score": 6, "confidence_reason": "Described as intermediary in notes; no corporate records confirm role", "source": "notes.txt:Lines 1-50"},
        {"id": "org1", "name": "Meridian Holdings Ltd", "type": "Organization", "properties": {"jurisdiction": "British Virgin Islands", "registration": "BVI-2019-44521"}, "evidence": "Meridian Holdings Ltd, incorporated in the BVI", "confidence": "high", "confidence_score": 10, "confidence_reason": "Registration number and jurisdiction explicitly stated", "source": "investigation_report.pdf:Page 1"},
        {"id": "org2", "name": "Pinnacle Trading LLC", "type": "Organization", "properties": {"jurisdiction": "Delaware, USA"}, "evidence": "Pinnacle Trading LLC, a Delaware shell company", "confidence": "high", "confidence_score": 9, "confidence_reason": "Clearly identified as Delaware entity in report", "source": "investigation_report.pdf:Page 2"},
        {"id": "org3", "name": "Golden Bridge Consulting", "type": "Organization", "properties": {"jurisdiction": "Dubai, UAE"}, "evidence": "Golden Bridge Consulting based in Dubai", "confidence": "high", "confidence_score": 8, "confidence_reason": "Named in corporate records with Dubai address", "source": "corporate_records.docx:Paragraph 7"},
        {"id": "org4", "name": "Lakeview Properties SA", "type": "Organization", "properties": {"jurisdiction": "Panama"}, "evidence": "Lakeview Properties SA, Panamanian entity", "confidence": "medium", "confidence_score": 6, "confidence_reason": "Mentioned in corporate records but limited detail on structure", "source": "corporate_records.docx:Paragraph 12"},
        {"id": "acc1", "name": "HSBC Acc: 4491-7823-001", "type": "Account", "properties": {"bank": "HSBC London", "currency": "GBP"}, "evidence": "HSBC account ending 001", "confidence": "high", "confidence_score": 9, "confidence_reason": "Account number explicitly stated in investigation report", "source": "investigation_report.pdf:Page 3"},
        {"id": "acc2", "name": "Deutsche Bank Acc: DE89-3704-0044", "type": "Account", "properties": {"bank": "Deutsche Bank Frankfurt", "currency": "EUR"}, "evidence": "Deutsche Bank account in Frankfurt", "confidence": "high", "confidence_score": 9, "confidence_reason": "Full IBAN provided in bank records", "source": "investigation_report.pdf:Page 3"},
        {"id": "acc3", "name": "Emirates NBD Acc: AE07-0331", "type": "Account", "properties": {"bank": "Emirates NBD Dubai", "currency": "USD"}, "evidence": "Emirates NBD account used for transfers", "confidence": "medium", "confidence_score": 6, "confidence_reason": "Account referenced in notes without full verification", "source": "notes.txt:Lines 1-50"},
        {"id": "acc4", "name": "Banistmo Acc: PA-5567-22", "type": "Account", "properties": {"bank": "Banistmo Panama", "currency": "USD"}, "evidence": "Banistmo Panama account", "confidence": "medium", "confidence_score": 5, "confidence_reason": "Account mentioned in corporate records, limited corroboration", "source": "corporate_records.docx:Paragraph 15"},
        {"id": "ph1", "name": "+44 7911 234567", "type": "Phone", "properties": {"carrier": "Vodafone UK"}, "evidence": "UK mobile number registered to Petrov", "confidence": "high", "confidence_score": 8, "confidence_reason": "Phone registration records confirm ownership", "source": "notes.txt:Lines 1-50"},
        {"id": "ph2", "name": "+971 50 123 4567", "type": "Phone", "properties": {"carrier": "Etisalat"}, "evidence": "UAE phone used in communications", "confidence": "medium", "confidence_score": 5, "confidence_reason": "Number appears in call records but owner not formally confirmed", "source": "notes.txt:Lines 51-100"},
        {"id": "addr1", "name": "14 Belgravia Sq, London SW1", "type": "Address", "properties": {"type": "Residential"}, "evidence": "London residence at Belgravia Square", "confidence": "high", "confidence_score": 9, "confidence_reason": "Address confirmed in multiple documents", "source": "investigation_report.pdf:Page 2"},
        {"id": "addr2", "name": "DIFC Gate Building, Dubai", "type": "Address", "properties": {"type": "Office"}, "evidence": "Dubai office in DIFC", "confidence": "high", "confidence_score": 8, "confidence_reason": "Registered office address in corporate filings", "source": "corporate_records.docx:Paragraph 7"},
        {"id": "em1", "name": "v.petrov@meridian-holdings.com", "type": "Email", "properties": {}, "evidence": "corporate email for Petrov", "confidence": "high", "confidence_score": 8, "confidence_reason": "Email appears in multiple communications and filings", "source": "notes.txt:Lines 1-50"},
        {"id": "mt1", "name": "Wire Transfer: 2.3M GBP (Jan 2023)", "type": "MoneyTransfer", "properties": {"amount": "2,300,000 GBP", "date": "2023-01-15", "reference": "WT-2023-0115"}, "evidence": "wire transfer of 2.3 million GBP on 15 January 2023", "confidence": "high", "confidence_score": 10, "confidence_reason": "Transaction confirmed in HSBC bank records with reference number", "source": "investigation_report.pdf:Page 3"},
        {"id": "mt2", "name": "Wire Transfer: 890K EUR (Mar 2023)", "type": "MoneyTransfer", "properties": {"amount": "890,000 EUR", "date": "2023-03-22", "reference": "WT-2023-0322"}, "evidence": "890,000 EUR transferred in March 2023", "confidence": "high", "confidence_score": 9, "confidence_reason": "Transfer confirmed in Deutsche Bank records", "source": "investigation_report.pdf:Page 3"},
        {"id": "mt3", "name": "Wire Transfer: 1.5M USD (Jun 2023)", "type": "MoneyTransfer", "properties": {"amount": "1,500,000 USD", "date": "2023-06-10", "reference": "WT-2023-0610"}, "evidence": "USD 1.5 million sent to Panama", "confidence": "medium", "confidence_score": 6, "confidence_reason": "Amount referenced in notes but not yet confirmed by bank records", "source": "notes.txt:Lines 51-100"},
        {"id": "ev1", "name": "Board Meeting - Dec 2022", "type": "Event", "properties": {"date": "2022-12-05", "location": "Dubai"}, "evidence": "board meeting in Dubai, December 2022", "confidence": "medium", "confidence_score": 6, "confidence_reason": "Meeting mentioned in corporate records but no minutes available", "source": "corporate_records.docx:Paragraph 20"},
        {"id": "loc1", "name": "British Virgin Islands", "type": "Location", "properties": {"type": "Jurisdiction"}, "evidence": "incorporated in the BVI", "confidence": "high", "confidence_score": 10, "confidence_reason": "Jurisdiction confirmed by registration documents", "source": "investigation_report.pdf:Page 1"},
        {"id": "doc1", "name": "Nominee Agreement (2019)", "type": "Document", "properties": {"date": "2019-08-14", "type": "Legal Agreement"}, "evidence": "nominee agreement dated August 2019", "confidence": "high", "confidence_score": 9, "confidence_reason": "Physical document copy referenced in corporate records", "source": "corporate_records.docx:Paragraph 3"},
    ]

    demo_relationships = [
        {"from_id": "p1", "to_id": "org1", "type": "ceo_of", "label": "CEO / Beneficial Owner\n100% Owner", "properties": {"percentage": "100", "start_date": "2019", "end_date": "Present"}, "evidence": "Viktor Petrov is the beneficial owner and CEO of Meridian Holdings", "confidence": "high", "confidence_score": 9, "confidence_reason": "Explicitly stated in investigation report with supporting corporate records", "source": "investigation_report.pdf:Page 1"},
        {"from_id": "p2", "to_id": "org1", "type": "works_for", "label": "CFO\n2019 - 2023", "properties": {"start_date": "2019", "end_date": "2023"}, "evidence": "Elena Vasquez served as CFO of Meridian Holdings", "confidence": "high", "confidence_score": 9, "confidence_reason": "Role confirmed in both investigation report and corporate filings", "source": "investigation_report.pdf:Page 1"},
        {"from_id": "p3", "to_id": "org1", "type": "director_of", "label": "Nominee Director\n2019 - Present", "properties": {"start_date": "2019", "end_date": "Present"}, "evidence": "James Thornton acted as nominee director", "confidence": "high", "confidence_score": 8, "confidence_reason": "Nominee agreement on file in corporate records", "source": "corporate_records.docx:Paragraph 3"},
        {"from_id": "p3", "to_id": "doc1", "type": "signed", "label": "signed nominee agreement", "evidence": "Thornton signed the nominee agreement", "confidence": "high", "confidence_score": 8, "confidence_reason": "Signature confirmed in corporate records", "source": "corporate_records.docx:Paragraph 3"},
        {"from_id": "p1", "to_id": "org2", "type": "controls", "label": "shadow director", "evidence": "Petrov controlled Pinnacle Trading through intermediaries", "confidence": "medium", "confidence_score": 5, "confidence_reason": "Control is inferred from communication patterns, not formally documented", "source": "investigation_report.pdf:Page 2"},
        {"from_id": "org1", "to_id": "org2", "type": "shareholder_of", "label": "100% Owner\n2019 - Present", "properties": {"percentage": "100", "start_date": "2019", "end_date": "Present"}, "evidence": "Meridian Holdings owns 100% of Pinnacle Trading", "confidence": "high", "confidence_score": 10, "confidence_reason": "Ownership confirmed in corporate registration documents", "source": "investigation_report.pdf:Page 2"},
        {"from_id": "p5", "to_id": "org3", "type": "managed_by", "label": "Managing Director\n2020 - Present", "properties": {"start_date": "2020", "end_date": "Present"}, "evidence": "Al-Rashid manages Golden Bridge Consulting", "confidence": "medium", "confidence_score": 6, "confidence_reason": "Role stated in notes but not confirmed by UAE corporate registry", "source": "notes.txt:Lines 1-50"},
        {"from_id": "org1", "to_id": "org3", "type": "associated_with", "label": "consulting arrangement", "evidence": "Meridian had a consulting arrangement with Golden Bridge", "confidence": "medium", "confidence_score": 5, "confidence_reason": "Arrangement mentioned but no contract copy available", "source": "corporate_records.docx:Paragraph 7"},
        {"from_id": "p1", "to_id": "org4", "type": "controls", "label": "ultimate beneficiary", "evidence": "Petrov identified as ultimate beneficiary of Lakeview Properties", "confidence": "medium", "confidence_score": 5, "confidence_reason": "Beneficial ownership inferred from financial flows, not directly documented", "source": "corporate_records.docx:Paragraph 12"},
        {"from_id": "org1", "to_id": "acc1", "type": "owns", "label": "corporate account", "evidence": "Meridian's primary HSBC account", "confidence": "high", "confidence_score": 9, "confidence_reason": "Account ownership confirmed by HSBC records", "source": "investigation_report.pdf:Page 3"},
        {"from_id": "org2", "to_id": "acc2", "type": "owns", "label": "corporate account", "evidence": "Pinnacle Trading's Deutsche Bank account", "confidence": "high", "confidence_score": 9, "confidence_reason": "Account ownership confirmed by Deutsche Bank records", "source": "investigation_report.pdf:Page 3"},
        {"from_id": "org3", "to_id": "acc3", "type": "owns", "label": "corporate account", "evidence": "Golden Bridge Emirates NBD account", "confidence": "medium", "confidence_score": 6, "confidence_reason": "Account referenced in notes, bank confirmation pending", "source": "notes.txt:Lines 1-50"},
        {"from_id": "org4", "to_id": "acc4", "type": "owns", "label": "corporate account", "evidence": "Lakeview Banistmo account", "confidence": "medium", "confidence_score": 5, "confidence_reason": "Account mentioned in corporate records without bank verification", "source": "corporate_records.docx:Paragraph 15"},
        {"from_id": "acc1", "to_id": "mt1", "type": "transferred_money_to", "label": "source: 2.3M GBP", "evidence": "2.3M GBP originated from HSBC account", "confidence": "high", "confidence_score": 10, "confidence_reason": "Transaction confirmed in HSBC bank statement with matching reference", "source": "investigation_report.pdf:Page 3"},
        {"from_id": "mt1", "to_id": "acc2", "type": "transferred_money_to", "label": "received 2.3M GBP", "evidence": "funds received at Deutsche Bank", "confidence": "high", "confidence_score": 10, "confidence_reason": "Receipt confirmed in Deutsche Bank statement", "source": "investigation_report.pdf:Page 3"},
        {"from_id": "acc2", "to_id": "mt2", "type": "transferred_money_to", "label": "source: 890K EUR", "evidence": "890K EUR sent from Deutsche Bank account", "confidence": "high", "confidence_score": 9, "confidence_reason": "Outgoing transfer confirmed in Deutsche Bank records", "source": "investigation_report.pdf:Page 3"},
        {"from_id": "mt2", "to_id": "acc3", "type": "transferred_money_to", "label": "received 890K EUR", "evidence": "funds received at Emirates NBD", "confidence": "medium", "confidence_score": 6, "confidence_reason": "Receipt noted in investigation but Emirates NBD records not yet obtained", "source": "notes.txt:Lines 51-100"},
        {"from_id": "acc3", "to_id": "mt3", "type": "transferred_money_to", "label": "source: 1.5M USD", "evidence": "1.5M USD sent from Emirates NBD", "confidence": "medium", "confidence_score": 5, "confidence_reason": "Transfer referenced in notes but bank records pending", "source": "notes.txt:Lines 51-100"},
        {"from_id": "mt3", "to_id": "acc4", "type": "transferred_money_to", "label": "received 1.5M USD", "evidence": "funds received at Banistmo Panama", "confidence": "medium", "confidence_score": 5, "confidence_reason": "Receipt inferred from notes, Banistmo records not obtained", "source": "notes.txt:Lines 51-100"},
        {"from_id": "p4", "to_id": "mt1", "type": "associated_with", "label": "processed wire transfer", "evidence": "Maria Santos processed the wire transfer", "confidence": "medium", "confidence_score": 6, "confidence_reason": "Processing role stated in notes, not confirmed by bank", "source": "notes.txt:Lines 1-50"},
        {"from_id": "p4", "to_id": "mt2", "type": "associated_with", "label": "processed wire transfer", "evidence": "Santos also processed the EUR transfer", "confidence": "medium", "confidence_score": 6, "confidence_reason": "Same source as above, consistent but unverified", "source": "notes.txt:Lines 1-50"},
        {"from_id": "p5", "to_id": "p1", "type": "met_with", "label": "met at Dubai board meeting", "evidence": "Al-Rashid met Petrov at the December 2022 board meeting", "confidence": "medium", "confidence_score": 6, "confidence_reason": "Meeting attendance mentioned in corporate records but no sign-in sheet", "source": "corporate_records.docx:Paragraph 20"},
        {"from_id": "p1", "to_id": "p2", "type": "family", "label": "Husband & Wife", "properties": {"family_type": "Husband & Wife"}, "evidence": "Petrov and Vasquez are married", "confidence": "high", "confidence_score": 8, "confidence_reason": "Marriage confirmed in property records", "source": "investigation_report.pdf:Page 4"},
        {"from_id": "p1", "to_id": "ph1", "type": "registered_to", "label": "personal phone", "evidence": "UK phone registered to Petrov", "confidence": "high", "confidence_score": 8, "confidence_reason": "Registration confirmed by carrier records", "source": "notes.txt:Lines 1-50"},
        {"from_id": "p5", "to_id": "ph2", "type": "registered_to", "label": "personal phone", "evidence": "UAE phone used by Al-Rashid", "confidence": "medium", "confidence_score": 5, "confidence_reason": "Phone attributed to Al-Rashid in notes but carrier records not checked", "source": "notes.txt:Lines 51-100"},
        {"from_id": "ph1", "to_id": "ph2", "type": "communicated_with", "label": "12 calls (Nov-Dec 2022)", "evidence": "phone records show 12 calls between the two numbers", "confidence": "high", "confidence_score": 9, "confidence_reason": "Call detail records confirm 12 calls in the stated period", "source": "notes.txt:Lines 51-100"},
        {"from_id": "p1", "to_id": "addr1", "type": "located_at", "label": "residence", "evidence": "Petrov resides at Belgravia Square", "confidence": "high", "confidence_score": 9, "confidence_reason": "Address confirmed by utility records and corporate filings", "source": "investigation_report.pdf:Page 2"},
        {"from_id": "org3", "to_id": "addr2", "type": "located_at", "label": "registered office", "evidence": "Golden Bridge registered at DIFC", "confidence": "high", "confidence_score": 8, "confidence_reason": "DIFC address listed in corporate registration", "source": "corporate_records.docx:Paragraph 7"},
        {"from_id": "p1", "to_id": "em1", "type": "registered_to", "label": "corporate email", "evidence": "Petrov's corporate email", "confidence": "high", "confidence_score": 8, "confidence_reason": "Email domain matches company, used in multiple communications", "source": "notes.txt:Lines 1-50"},
        {"from_id": "p1", "to_id": "ev1", "type": "associated_with", "label": "attended board meeting", "evidence": "Petrov attended the December board meeting in Dubai", "confidence": "medium", "confidence_score": 6, "confidence_reason": "Attendance mentioned in records but no formal minutes available", "source": "corporate_records.docx:Paragraph 20"},
        {"from_id": "org1", "to_id": "loc1", "type": "located_at", "label": "jurisdiction of incorporation", "evidence": "incorporated in the BVI", "confidence": "high", "confidence_score": 10, "confidence_reason": "BVI registration documents on file", "source": "investigation_report.pdf:Page 1"},
    ]

    return demo_entities, demo_relationships


def _seed_test_project():
    db = SessionLocal()
    try:
        existing = db.query(Project).filter(Project.name == "Test Project").first()
        if existing:
            return
        system_user = db.query(User).first()
        if not system_user:
            from auth import hash_password
            system_user = User(username="system", password_hash=hash_password("system"))
            db.add(system_user)
            db.commit()
            db.refresh(system_user)
        project = Project(name="Test Project",
                          description="Pre-loaded demo data for exploration (Meridian Holdings case)",
                          created_by=system_user.id)
        db.add(project)
        db.commit()
        db.refresh(project)
        demo_entities, demo_relationships = _get_demo_data()
        snap = GraphSnapshot(project_id=project.id,
                             entities=json.dumps(demo_entities),
                             relationships=json.dumps(demo_relationships))
        db.add(snap)
        db.commit()
        print(f"[SEED] Test Project created (id={project.id}) with {len(demo_entities)} entities, {len(demo_relationships)} relationships")
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════
# AUDIT LOG
# ═══════════════════════════════════════════════════════════════

@app.get("/api/audit-log")
async def get_audit_log(limit: int = 200, offset: int = 0,
                        user: dict = Depends(get_current_user)):
    entries = get_log(limit, offset)
    return JSONResponse({"entries": entries, "total": len(entries)})


# ═══════════════════════════════════════════════════════════════
# PATH FINDER
# ═══════════════════════════════════════════════════════════════

@app.post("/api/path/find")
async def find_path(request: Request,
                    user: dict = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    body = await request.json()
    project_id = body.get("project_id")
    from_id = body.get("from_id", "")
    to_id = body.get("to_id", "")
    max_depth = body.get("max_depth", 10)
    if not project_id:
        raise HTTPException(400, "project_id required")
    gs = _load_graph(project_id, db)
    result = find_shortest_path(gs["entities"], gs["relationships"],
                                from_id, to_id, max_depth)
    log_action("find_path", user=user.get("username", ""),
               details={"from": from_id, "to": to_id, "found": result.get("found", False)})
    return JSONResponse(result)


@app.post("/api/path/all")
async def find_all(request: Request,
                   user: dict = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    body = await request.json()
    project_id = body.get("project_id")
    from_id = body.get("from_id", "")
    to_id = body.get("to_id", "")
    max_depth = body.get("max_depth", 5)
    if not project_id:
        raise HTTPException(400, "project_id required")
    gs = _load_graph(project_id, db)
    results = find_all_paths(gs["entities"], gs["relationships"],
                             from_id, to_id, max_depth, max_paths=10)
    return JSONResponse({"paths": results})


# ═══════════════════════════════════════════════════════════════
# AI CHAT
# ═══════════════════════════════════════════════════════════════

@app.post("/api/chat")
async def ai_chat(request: Request,
                  user: dict = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    body = await request.json()
    project_id = body.get("project_id")
    question = body.get("question", "")

    if not question:
        return JSONResponse({"error": "No question provided"}, status_code=400)
    if not project_id:
        raise HTTPException(400, "project_id required")

    gs = _load_graph(project_id, db)

    entities_summary = []
    for e in gs["entities"]:
        props = ", ".join(f"{k}={v}" for k, v in e.get("properties", {}).items())
        entities_summary.append(f"- {e['name']} (type={e.get('type')}, confidence={e.get('confidence')}, props={props})")

    rels_summary = []
    eid_name = {e["id"]: e["name"] for e in gs["entities"]}
    for r in gs["relationships"]:
        fn = eid_name.get(r["from_id"], r["from_id"])
        tn = eid_name.get(r["to_id"], r["to_id"])
        rels_summary.append(f"- {fn} --[{r.get('type')}]--> {tn} (label={r.get('label')}, confidence={r.get('confidence')})")

    graph_ctx = f"ENTITIES ({len(gs['entities'])}):\n" + "\n".join(entities_summary[:100])
    graph_ctx += f"\n\nRELATIONSHIPS ({len(gs['relationships'])}):\n" + "\n".join(rels_summary[:100])

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
        from ai_extraction import _call_llm
        answer = _call_llm(system, user_msg, max_tokens=1024)
        log_action("ai_chat", user=user.get("username", ""), details={"question": question[:100]})
        return JSONResponse({"answer": answer})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ═══════════════════════════════════════════════════════════════
# BULK REVIEW
# ═══════════════════════════════════════════════════════════════

@app.get("/api/review/items")
async def get_review_items(project_id: int = Query(...),
                           threshold: int = 10,
                           user: dict = Depends(get_current_user),
                           db: Session = Depends(get_db)):
    gs = _load_graph(project_id, db)
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


@app.post("/api/review/accept")
async def review_accept(request: Request,
                        user: dict = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    body = await request.json()
    project_id = body.get("project_id")
    item_id = body.get("id", "")
    if not project_id:
        raise HTTPException(400, "project_id required")
    gs = _load_graph(project_id, db)
    rejected = gs.get("rejected_items", [])
    _push_undo(project_id, gs["entities"], gs["relationships"], rejected)
    if item_id.startswith("edge_"):
        idx = int(item_id.replace("edge_", ""))
        if 0 <= idx < len(gs["relationships"]):
            gs["relationships"][idx]["confidence"] = "high"
            gs["relationships"][idx]["confidence_score"] = 10
    else:
        for e in gs["entities"]:
            if e["id"] == item_id:
                e["confidence"] = "high"
                e["confidence_score"] = 10
                break
    _save_graph(project_id, gs["entities"], gs["relationships"], gs["errors"], db,
                rejected_items=rejected)
    log_action("review_accept", user=user.get("username", ""), details={"item_id": item_id})
    graph_data = build_graph_data(gs["entities"], gs["relationships"])
    return JSONResponse({"success": True, "graph": graph_data,
                         "entity_count": len(gs["entities"]),
                         "relationship_count": len(gs["relationships"])})


@app.post("/api/review/reject")
async def review_reject(request: Request,
                        user: dict = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    body = await request.json()
    project_id = body.get("project_id")
    item_id = body.get("id", "")
    if not project_id:
        raise HTTPException(400, "project_id required")
    gs = _load_graph(project_id, db)
    rejected = gs.get("rejected_items", [])
    _push_undo(project_id, gs["entities"], gs["relationships"], rejected)
    eid_name = {e["id"]: e.get("name", e["id"]) for e in gs["entities"]}
    removed_item = None
    if item_id.startswith("edge_"):
        idx = int(item_id.replace("edge_", ""))
        if 0 <= idx < len(gs["relationships"]):
            removed_item = gs["relationships"].pop(idx)
            removed_item["_rejected_kind"] = "relationship"
            removed_item["_from_name"] = eid_name.get(removed_item.get("from_id", ""), removed_item.get("from_id", ""))
            removed_item["_to_name"] = eid_name.get(removed_item.get("to_id", ""), removed_item.get("to_id", ""))
    else:
        for e in gs["entities"]:
            if e["id"] == item_id:
                removed_item = dict(e)
                removed_item["_rejected_kind"] = "entity"
                break
        gs["entities"] = [e for e in gs["entities"] if e["id"] != item_id]
        gs["relationships"] = [r for r in gs["relationships"]
                               if r["from_id"] != item_id and r["to_id"] != item_id]
    if removed_item:
        from datetime import datetime, timezone
        removed_item["_rejected_at"] = datetime.now(timezone.utc).isoformat()
        rejected.append(removed_item)
    _save_graph(project_id, gs["entities"], gs["relationships"], gs["errors"], db,
                rejected_items=rejected)
    log_action("review_reject", user=user.get("username", ""), details={"item_id": item_id})
    graph_data = build_graph_data(gs["entities"], gs["relationships"])
    return JSONResponse({"success": True, "graph": graph_data,
                         "entity_count": len(gs["entities"]),
                         "relationship_count": len(gs["relationships"]),
                         "rejected_count": len(rejected)})


@app.get("/api/review/rejected")
async def get_rejected_items(project_id: int = Query(...),
                             user: dict = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    gs = _load_graph(project_id, db)
    rejected = gs.get("rejected_items", [])
    eid_name = {e["id"]: e.get("name", e["id"]) for e in gs["entities"]}
    items = []
    for i, r in enumerate(rejected):
        kind = r.get("_rejected_kind", "entity")
        name = r.get("name", "")
        if kind == "relationship":
            fn = r.get("_from_name") or eid_name.get(r.get("from_id", ""), r.get("from_id", ""))
            tn = r.get("_to_name") or eid_name.get(r.get("to_id", ""), r.get("to_id", ""))
            name = f"{fn} -> {tn}"
        items.append({
            "index": i, "kind": kind, "name": name,
            "type": r.get("type", ""),
            "label": r.get("label", ""),
            "evidence": r.get("evidence", ""),
            "source": r.get("source", ""),
            "confidence": r.get("confidence", ""),
            "confidence_score": r.get("confidence_score", 0),
            "confidence_reason": r.get("confidence_reason", ""),
            "rejected_at": r.get("_rejected_at", ""),
        })
    return JSONResponse({"items": items, "total": len(items)})


@app.post("/api/review/restore")
async def review_restore(request: Request,
                         user: dict = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    body = await request.json()
    project_id = body.get("project_id")
    index = body.get("index")
    if not project_id or index is None:
        raise HTTPException(400, "project_id and index required")
    gs = _load_graph(project_id, db)
    rejected = gs.get("rejected_items", [])
    _push_undo(project_id, gs["entities"], gs["relationships"], rejected)
    if 0 <= index < len(rejected):
        item = rejected.pop(index)
        kind = item.pop("_rejected_kind", "entity")
        item.pop("_rejected_at", None)
        item.pop("_from_name", None)
        item.pop("_to_name", None)
        if kind == "entity":
            gs["entities"].append(item)
        else:
            gs["relationships"].append(item)
    _save_graph(project_id, gs["entities"], gs["relationships"], gs["errors"], db,
                rejected_items=rejected)
    log_action("review_restore", user=user.get("username", ""), details={"index": index})
    graph_data = build_graph_data(gs["entities"], gs["relationships"])
    return JSONResponse({"success": True, "graph": graph_data,
                         "entity_count": len(gs["entities"]),
                         "relationship_count": len(gs["relationships"])})


# ═══════════════════════════════════════════════════════════════
# DOCUMENT VIEWER
# ═══════════════════════════════════════════════════════════════

@app.get("/api/documents")
async def list_documents(project_id: int = Query(...),
                         user: dict = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    records = db.query(DocumentRecord).filter(
        DocumentRecord.project_id == project_id).all()
    docs = []
    for r in records:
        ext = os.path.splitext(r.original_name)[1].lower()
        docs.append({"name": r.original_name, "ext": ext,
                     "available": os.path.exists(r.file_path)})
    return JSONResponse({"documents": docs})


@app.get("/api/document/{filename}")
async def serve_document(filename: str,
                         project_id: int = Query(...),
                         user: dict = Depends(get_current_user),
                         db: Session = Depends(get_db)):
    record = db.query(DocumentRecord).filter(
        DocumentRecord.project_id == project_id,
        DocumentRecord.original_name == filename).first()
    if not record or not os.path.exists(record.file_path):
        return JSONResponse({"error": "File not found"}, status_code=404)
    ext = os.path.splitext(filename)[1].lower()
    media_types = {".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/plain"}
    media = media_types.get(ext, "application/octet-stream")
    with open(record.file_path, "rb") as f:
        content = f.read()
    return Response(content=content, media_type=media,
                    headers={"Content-Disposition": f'inline; filename="{filename}"'})


# ═══════════════════════════════════════════════════════════════
# REPORT EXPORT
# ═══════════════════════════════════════════════════════════════

@app.get("/api/export/report")
async def export_report(project_id: int = Query(...),
                        token: str = Query(""),
                        user: dict = Depends(get_current_user_or_token),
                        db: Session = Depends(get_db)):
    gs = _load_graph(project_id, db)
    entities = gs["entities"]
    relationships = gs["relationships"]
    eid_name = {e["id"]: e["name"] for e in entities}

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")

    entity_rows = ""
    for e in sorted(entities, key=lambda x: x.get("type", "")):
        props = ", ".join(f"{k}: {v}" for k, v in e.get("properties", {}).items())
        score = e.get("confidence_score", "?")
        entity_rows += f"<tr><td>{e.get('name','')}</td><td>{e.get('type','')}</td><td>{score}/10</td><td>{props}</td><td>{e.get('source','')}</td></tr>\n"

    rel_rows = ""
    for r in relationships:
        fn = eid_name.get(r["from_id"], r["from_id"])
        tn = eid_name.get(r["to_id"], r["to_id"])
        score = r.get("confidence_score", "?")
        rel_rows += f"<tr><td>{fn}</td><td>{r.get('label', r.get('type',''))}</td><td>{tn}</td><td>{score}/10</td><td>{r.get('source','')}</td></tr>\n"

    high = sum(1 for e in entities if e.get("confidence") == "high")
    med = sum(1 for e in entities if e.get("confidence") == "medium")
    low = sum(1 for e in entities if e.get("confidence") == "low")

    audit_entries = get_log(50)
    audit_rows = ""
    for a in audit_entries[:50]:
        audit_rows += f"<tr><td>{a.get('timestamp','')}</td><td>{a.get('action','')}</td><td>{a.get('user','')}</td><td>{json.dumps(a.get('details',{}))[:120]}</td></tr>\n"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Forensic Graph Intelligence Report</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 40px; color: #222; font-size: 11px; }}
h1 {{ font-size: 18px; border-bottom: 2px solid #333; padding-bottom: 8px; }}
h2 {{ font-size: 14px; margin-top: 24px; border-bottom: 1px solid #999; padding-bottom: 4px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 10px; }}
th, td {{ border: 1px solid #ccc; padding: 4px 6px; text-align: left; }}
th {{ background: #f0f0f0; font-weight: 600; }}
.summary {{ display: flex; gap: 20px; margin: 12px 0; }}
.summary div {{ padding: 8px 16px; border: 1px solid #ccc; border-radius: 4px; text-align: center; }}
.summary .val {{ font-size: 20px; font-weight: bold; }}
.summary .lbl {{ font-size: 9px; color: #666; text-transform: uppercase; }}
.footer {{ margin-top: 30px; font-size: 9px; color: #888; border-top: 1px solid #ccc; padding-top: 8px; }}
@media print {{ body {{ margin: 20px; }} }}
</style></head><body>
<h1>Forensic Graph Intelligence Report</h1>
<p>Generated: {ts}</p>
<div class="summary">
<div><div class="val">{len(entities)}</div><div class="lbl">Entities</div></div>
<div><div class="val">{len(relationships)}</div><div class="lbl">Relationships</div></div>
<div><div class="val">{high}</div><div class="lbl">High Confidence</div></div>
<div><div class="val">{med}</div><div class="lbl">Medium</div></div>
<div><div class="val">{low}</div><div class="lbl">Low / Review</div></div>
</div>
<h2>Entities ({len(entities)})</h2>
<table><tr><th>Name</th><th>Type</th><th>Score</th><th>Properties</th><th>Source</th></tr>
{entity_rows}</table>
<h2>Relationships ({len(relationships)})</h2>
<table><tr><th>From</th><th>Relationship</th><th>To</th><th>Score</th><th>Source</th></tr>
{rel_rows}</table>
<h2>Audit Log (last 50 entries)</h2>
<table><tr><th>Timestamp</th><th>Action</th><th>User</th><th>Details</th></tr>
{audit_rows}</table>
<div class="footer">
This report was generated by the Forensic Graph Intelligence system. All extractions include AI confidence scores (1-10).
Items with scores below 5 should be independently verified against source documents.
</div>
</body></html>"""

    return Response(content=html, media_type="text/html",
                    headers={"Content-Disposition": 'inline; filename="forensic-report.html"'})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8050)
