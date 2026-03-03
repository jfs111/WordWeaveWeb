# services/service_a/app/api/storage.py
"""Storage API — Qdrant operations, search, embeddings"""

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from uuid import UUID
import logging

from app.services.qdrant_manager import QdrantManager

router = APIRouter()
logger = logging.getLogger("service-a.storage")

# ── Pydantic Models ──

class IngestChunkRequest(BaseModel):
    chunk_id: str
    text: str
    embedding: List[float]
    metadata: Dict[str, Any] = {}

class IngestBatchRequest(BaseModel):
    owner_id: str
    project_id: str
    chunks: List[IngestChunkRequest]

class SearchRequest(BaseModel):
    owner_id: str
    project_id: str
    query_embedding: List[float]
    n_results: int = Field(default=10, ge=1, le=100)
    where_filter: Optional[Dict[str, Any]] = None

class SearchResult(BaseModel):
    chunk_id: str
    text: str
    metadata: Dict[str, Any]
    distance: float
    score: float

class StatsResponse(BaseModel):
    total_chunks: int
    collection_name: str


# ── Dependency ──
_manager = None

def get_manager():
    global _manager
    if _manager is None:
        _manager = QdrantManager()
    return _manager


# ── Endpoints ──

@router.post("/projects/{owner_id}/{project_id}/ingest")
async def ingest_chunks(
    owner_id: str,
    project_id: str,
    request: IngestBatchRequest,
    manager: QdrantManager = Depends(get_manager)
):
    """Ingest chunks into project-isolated Qdrant collection"""
    try:
        result = manager.ingest_batch(owner_id, project_id, request.chunks)
        return {"status": "ok", "ingested": result["count"], "collection": result["collection"]}
    except Exception as e:
        logger.error(f"Ingest error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/projects/{owner_id}/{project_id}/search", response_model=List[SearchResult])
async def search_chunks(
    owner_id: str,
    project_id: str,
    request: SearchRequest,
    manager: QdrantManager = Depends(get_manager)
):
    """Semantic search within a project's Qdrant collection"""
    try:
        results = manager.search(owner_id, project_id, request.query_embedding, request.n_results, request.where_filter)
        return results
    except Exception as e:
        logger.error(f"Search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{owner_id}/{project_id}/chunks/{chunk_id}")
async def get_chunk(
    owner_id: str,
    project_id: str,
    chunk_id: str,
    manager: QdrantManager = Depends(get_manager)
):
    """Get a specific chunk by ID"""
    try:
        result = manager.get_chunk(owner_id, project_id, chunk_id)
        if not result:
            raise HTTPException(status_code=404, detail="Chunk not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{owner_id}/{project_id}/chunks")
async def list_chunks(
    owner_id: str,
    project_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    cluster_id: Optional[int] = None,
    manager: QdrantManager = Depends(get_manager)
):
    """List chunks in a project (with optional cluster filter)"""
    try:
        results = manager.list_chunks(owner_id, project_id, offset, limit, cluster_id)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{owner_id}/{project_id}/stats", response_model=StatsResponse)
async def get_stats(
    owner_id: str,
    project_id: str,
    manager: QdrantManager = Depends(get_manager)
):
    """Get collection stats for a project"""
    try:
        return manager.get_stats(owner_id, project_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/projects/{owner_id}/{project_id}")
async def delete_project_data(
    owner_id: str,
    project_id: str,
    manager: QdrantManager = Depends(get_manager)
):
    """Delete all Qdrant data for a project"""
    try:
        manager.delete_collection(owner_id, project_id)
        return {"status": "deleted", "owner_id": owner_id, "project_id": project_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{owner_id}/{project_id}/embeddings")
async def get_all_embeddings(
    owner_id: str,
    project_id: str,
    manager: QdrantManager = Depends(get_manager)
):
    """Get all embeddings and chunk IDs for a project (for clustering)"""
    try:
        return manager.get_all_embeddings(owner_id, project_id)
    except Exception as e:
        print(f"[Embeddings] Error: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))