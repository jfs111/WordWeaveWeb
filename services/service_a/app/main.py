# services/service_a/app/main.py
"""Service A — Data & Storage (Qdrant, PostgreSQL)"""

from fastapi import FastAPI
from app.api.health import router as health_router
from app.api.storage import router as storage_router
from app.api.storage_phase2 import router as storage_phase2_router

app = FastAPI(title="Word Weave Web Storage Service", version="3.0.0")

app.include_router(health_router)
app.include_router(storage_router, prefix="/storage", tags=["storage"])
app.include_router(storage_phase2_router, prefix="/storage", tags=["storage-phase2"])