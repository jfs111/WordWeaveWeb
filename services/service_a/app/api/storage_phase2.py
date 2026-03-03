# services/service_a/app/api/storage_phase2.py
"""Phase 2 additions to Storage API — bulk embeddings retrieval + cluster metadata update (Qdrant)"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import logging

from app.services.qdrant_manager import QdrantManager

router = APIRouter()
logger = logging.getLogger("service-a.storage-phase2")


# ── Models ──

class BulkEmbeddingsResponse(BaseModel):
    chunk_ids: List[str]
    embeddings: List[List[float]]
    documents: List[str]
    metadatas: List[Dict[str, Any]]
    total: int


class UpdateClusterRequest(BaseModel):
    updates: List[Dict[str, Any]]  # [{"chunk_id": "...", "cluster_id": 5}, ...]


# ── Dependency ──
_manager = None

def get_manager():
    global _manager
    if _manager is None:
        _manager = QdrantManager()
    return _manager


# ── Endpoints ──

@router.get("/projects/{owner_id}/{project_id}/embeddings", response_model=BulkEmbeddingsResponse)
async def get_all_embeddings(
    owner_id: str,
    project_id: str,
    manager: QdrantManager = Depends(get_manager)
):
    """Get ALL embeddings for a project (for clustering)"""
    try:
        data = manager.get_all_embeddings(owner_id, project_id)
        return BulkEmbeddingsResponse(**data)
    except Exception as e:
        logger.error(f"Bulk embeddings error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{owner_id}/{project_id}/update-clusters")
async def update_chunk_clusters(
    owner_id: str,
    project_id: str,
    request: UpdateClusterRequest,
    manager: QdrantManager = Depends(get_manager)
):
    """Update cluster_id metadata in Qdrant for chunks"""
    try:
        updated = manager.update_cluster_metadata(owner_id, project_id, request.updates)
        return {"status": "ok", "updated": updated}
    except Exception as e:
        logger.error(f"Update clusters error: {e}")
        raise HTTPException(status_code=500, detail=str(e))