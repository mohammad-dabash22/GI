"""Audit log routes."""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.services.auth_service import get_current_user
from app.services.audit_service import get_log

router = APIRouter(prefix="/api")


@router.get("/audit-log")
async def get_audit_log(
    limit: int = 200,
    offset: int = 0,
    user: dict = Depends(get_current_user),
):
    entries = get_log(limit, offset)
    return JSONResponse({"entries": entries, "total": len(entries)})
