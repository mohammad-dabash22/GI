"""Analysis routes — thin controller delegating to analysis_service."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.models import get_db
from app.services.auth_service import get_current_user
from app.services import analysis_service
from app.schemas.graph import FindPathRequest, FindAllPathsRequest, ChatRequest

router = APIRouter(prefix="/api")


@router.post("/path/find")
async def find_path(
    body: FindPathRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(analysis_service.find_path(
        body.project_id, body.from_id, body.to_id, body.max_depth,
        user.get("username", ""), db
    ))


@router.post("/path/all")
async def find_all(
    body: FindAllPathsRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(analysis_service.find_all(
        body.project_id, body.from_id, body.to_id, body.max_depth,
        user.get("username", ""), db
    ))


@router.post("/chat")
async def ai_chat(
    body: ChatRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = analysis_service.ai_chat(
        body.project_id, body.question, user.get("username", ""), db
    )
    status_code = result.pop("status_code", 200)
    return JSONResponse(result, status_code=status_code)
