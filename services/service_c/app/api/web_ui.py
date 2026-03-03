# services/service_c/app/api/web_ui.py
"""Web UI Routes — Serve HTML pages for the SPA-like interface"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pathlib import Path

router = APIRouter()

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def _read_template(name: str) -> str:
    return (TEMPLATES_DIR / name).read_text(encoding="utf-8")


@router.get("/", response_class=HTMLResponse)
async def login_page():
    """Login page (entry point)"""
    return _read_template("login.html")


@router.get("/register", response_class=HTMLResponse)
async def register_page():
    """Registration page"""
    return _read_template("register.html")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    """Main dashboard (after login)"""
    return _read_template("dashboard.html")


@router.get("/project/{project_id}", response_class=HTMLResponse)
async def project_page(project_id: str):
    """Project detail page"""
    return _read_template("project.html")
