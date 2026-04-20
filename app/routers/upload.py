"""Upload routes — thin controller delegating to upload_service."""

import json

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.models import get_db
from app.domain.document_types import DOCUMENT_TYPES
from app.services.auth_service import get_current_user
from app.services import upload_service
from app.core.graph_state import get_pipeline_status

router = APIRouter(prefix="/api")


@router.get("/document-types")
async def get_document_types(user: dict = Depends(get_current_user)):
    return JSONResponse({"types": DOCUMENT_TYPES})


@router.post("/upload")
async def upload_documents(
    files: list[UploadFile] = File(...),
    doc_types: str = Form("{}"),
    mode: str = Form("incremental"),
    project_id: int = Form(...),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = await upload_service.process_upload(
        files, doc_types, mode, project_id, user.get("username", ""), db
    )
    status_code = result.pop("status_code", 200)
    return JSONResponse(result, status_code=status_code)


@router.get("/pipeline/status")
async def pipeline_status(
    project_id: int = Query(...),
    user: dict = Depends(get_current_user),
):
    ps = get_pipeline_status(project_id)
    return JSONResponse({
        "running": ps["running"],
        "current_pass": ps["current_pass"],
        "pass_detail": ps["pass_detail"],
    })


@router.post("/upload-structured")
async def upload_structured(
    file: UploadFile = File(...),
    payload: str = Form(...),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ingest structured XLSX/CSV data (parsed client-side).

    Accepts multipart form: 'file' (the original CSV/XLSX) and 'payload'
    (JSON string with: project_id, mode, filename, mapping,
    default_entity_type, rows).
    """
    data = json.loads(payload)
    file_content = await file.read()
    result = upload_service.process_structured_upload(
        data, user.get("username", ""), db,
        file_content=file_content, original_filename=file.filename,
    )
    status_code = result.pop("status_code", 200)
    return JSONResponse(result, status_code=status_code)
