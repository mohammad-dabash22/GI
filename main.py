"""Application entrypoint. Run with: uvicorn main:app --reload"""
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from config import UPLOAD_DIR
from database import init_db, SessionLocal
from models import User, Project, GraphSnapshot
from auth import hash_password
from seed_data import get_demo_entities, get_demo_relationships

from routers import auth, pages, projects, upload, graph, review, analysis, audit, documents

app = FastAPI(title="Forensic Graph Intelligence")


# ── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
def on_startup():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    init_db()
    _seed_test_project()


# ── Global exception handler ─────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


# ── Static files & templates ─────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory="static"), name="static")


# ── Routers ──────────────────────────────────────────────────────────────────

app.include_router(pages.router)
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(upload.router)
app.include_router(graph.router)
app.include_router(review.router)
app.include_router(analysis.router)
app.include_router(audit.router)
app.include_router(documents.router)


# ── Seed ─────────────────────────────────────────────────────────────────────

def _seed_test_project():
    import json
    db = SessionLocal()
    try:
        if db.query(Project).filter(Project.name == "Test Project").first():
            return
        system_user = db.query(User).first()
        if not system_user:
            system_user = User(username="system", password_hash=hash_password("system"))
            db.add(system_user)
            db.commit()
            db.refresh(system_user)
        project = Project(name="Test Project", description="Pre-loaded demo investigation",
                          created_by=system_user.id)
        db.add(project)
        db.commit()
        db.refresh(project)
        demo_entities = get_demo_entities()
        demo_relationships = get_demo_relationships()
        snap = GraphSnapshot(
            project_id=project.id,
            entities=json.dumps(demo_entities),
            relationships=json.dumps(demo_relationships),
        )
        db.add(snap)
        db.commit()
        print(f"[SEED] Test Project created (id={project.id}) with "
              f"{len(demo_entities)} entities, {len(demo_relationships)} relationships")
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8050)
