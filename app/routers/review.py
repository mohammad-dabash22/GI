"""Review routes — thin controller delegating to review_service."""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.models import get_db
from app.services.auth_service import get_current_user
from app.services import review_service
from app.schemas.graph import ReviewActionRequest, ReviewRestoreRequest

router = APIRouter(prefix="/api")


@router.get("/review/items")
async def get_review_items(
    project_id: int = Query(...),
    threshold: int = 10,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(review_service.get_review_items(project_id, threshold, db))


@router.post("/review/accept")
async def review_accept(
    body: ReviewActionRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(review_service.accept_item(
        body.project_id, body.id, user.get("username", ""), db
    ))


@router.post("/review/reject")
async def review_reject(
    body: ReviewActionRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(review_service.reject_item(
        body.project_id, body.id, user.get("username", ""), db
    ))


@router.get("/review/rejected")
async def get_rejected_items(
    project_id: int = Query(...),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(review_service.get_rejected_items(project_id, db))


@router.post("/review/restore")
async def review_restore(
    body: ReviewRestoreRequest,
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return JSONResponse(review_service.restore_item(
        body.project_id, body.index, user.get("username", ""), db
    ))
