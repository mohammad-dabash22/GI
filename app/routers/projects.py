"""Project CRUD routes — thin controller delegating to project_service."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.models import get_db
from app.services.auth_service import get_current_user
from app.services import project_service
from app.schemas.projects import CreateProjectRequest, SavePositionsRequest

router = APIRouter(prefix="/api")


@router.get("/projects")
async def list_projects(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse({"projects": project_service.list_projects(db)})


@router.post("/projects")
async def create_project(
    body: CreateProjectRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = project_service.create_project(body.name, body.description, user["sub"], db)
    return JSONResponse(result)


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(project_service.delete_project(project_id, db))


@router.get("/projects/{project_id}")
async def get_project(
    project_id: int,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(project_service.get_project(project_id, db))


@router.post("/graph/positions")
async def save_positions(
    body: SavePositionsRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(project_service.save_positions(body.project_id, body.positions, db))
