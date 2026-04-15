"""Document routes — thin controller delegating to document_service."""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.models import get_db
from app.services.auth_service import get_current_user, get_current_user_or_token
from app.services import document_service

router = APIRouter(prefix="/api")


@router.get("/documents")
async def list_documents(
    project_id: int = Query(...),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    docs = document_service.list_documents(project_id, db)
    return JSONResponse({"documents": docs})


@router.get("/document/{filename}")
async def serve_document(
    filename: str,
    project_id: int = Query(...),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = document_service.serve_document(filename, project_id, db)
    if result is None:
        return JSONResponse({"error": "File not found"}, status_code=404)
    return result


@router.get("/export/report")
async def export_report(
    project_id: int = Query(...),
    token: str = Query(""),
    user: dict = Depends(get_current_user_or_token),
    db: Session = Depends(get_db),
):
    html = document_service.generate_report(project_id, db)
    return Response(
        content=html,
        media_type="text/html",
        headers={"Content-Disposition": 'inline; filename="forensic-report.html"'},
    )
