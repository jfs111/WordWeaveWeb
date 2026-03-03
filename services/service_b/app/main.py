# services/service_b/app/main.py
"""Service B — Intelligence (Embeddings, Clustering, Relations)"""

from fastapi import FastAPI
from app.api.health import router as health_router
from app.api.intelligence import router as intelligence_router
from app.api.intelligence_phase2 import router as intelligence_phase2_router

app = FastAPI(title="Graph-RAG Intelligence Service", version="2.0.0")

app.include_router(health_router)
app.include_router(intelligence_router, prefix="/intelligence", tags=["intelligence"])
app.include_router(intelligence_phase2_router, prefix="/intelligence", tags=["intelligence-phase2"])
