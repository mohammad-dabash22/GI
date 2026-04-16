"""Page rendering routes: serve HTML templates."""

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html")


@router.get("/projects")
async def projects_page(request: Request):
    return templates.TemplateResponse(request, "projects.html")


@router.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")
