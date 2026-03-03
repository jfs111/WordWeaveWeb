# services/service_c/app/main.py
"""Service C — Orchestrator + Web UI"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.web_ui import router as web_ui_router
from app.api.projects import router as projects_router
from app.api.documents import router as documents_router
from app.api.external_api import router as external_router
from app.api.analysis import router as analysis_router
from app.api.chat import router as chat_router
from app.api.doc_analysis import router as doc_analysis_router

app = FastAPI(title="Graph-RAG Orchestrator", version="3.0.0")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(health_router)
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(web_ui_router, tags=["web-ui"])
app.include_router(projects_router, prefix="/projects", tags=["projects"])
app.include_router(documents_router, prefix="/projects", tags=["documents"])
app.include_router(analysis_router, prefix="/projects", tags=["analysis"])
app.include_router(chat_router, prefix="/projects", tags=["chat"])
app.include_router(doc_analysis_router, prefix="/projects", tags=["doc-analysis"])
app.include_router(external_router, prefix="/api/v1", tags=["external-api"])
