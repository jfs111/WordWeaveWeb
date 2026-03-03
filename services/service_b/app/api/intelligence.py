# services/service_b/app/api/intelligence.py
"""Intelligence API — Chunking, Embeddings, Clustering, Relations"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Tuple
from uuid import uuid4
import logging

from app.services.chunker import TextChunker
from app.services.embedder import EmbeddingService
from app.services.clusterer import ClusteringService

router = APIRouter()
logger = logging.getLogger("service-b.intelligence")

# ── In-memory job tracking (Redis in production) ──
_jobs: Dict[str, Dict] = {}


# ── Request/Response Models ──

class ChunkRequest(BaseModel):
    text: str
    doc_id: str
    chunk_size: int = 1500
    chunk_overlap: int = 200
    metadata: Dict[str, Any] = {}

class ChunkResult(BaseModel):
    chunk_id: str
    text: str
    char_start: int
    char_end: int
    word_count: int
    position: int
    context_before: str = ""
    context_after: str = ""

class EmbedRequest(BaseModel):
    texts: List[str]

class EmbedResult(BaseModel):
    embeddings: List[List[float]]
    model: str
    dimension: int

class ClusterRequest(BaseModel):
    embeddings: List[List[float]]
    method: str = "auto-k"
    force_k: Optional[int] = None
    k_range: Optional[Tuple[int, int]] = None

class ClusterResult(BaseModel):
    labels: List[int]
    n_clusters: int
    silhouette_score: float
    davies_bouldin_score: float

class PipelineRequest(BaseModel):
    """Full pipeline: chunk → embed → cluster"""
    texts: List[Dict[str, Any]]  # [{doc_id, text, metadata}]
    chunk_size: int = 1500
    chunk_overlap: int = 200
    clustering_method: str = "auto-k"

class JobStatus(BaseModel):
    job_id: str
    status: str
    progress: float
    current_step: Optional[str] = None
    result: Optional[Dict] = None
    error: Optional[str] = None


# ── Endpoints ──

@router.post("/chunk", response_model=List[ChunkResult])
async def chunk_text(request: ChunkRequest):
    """Split text into overlapping chunks"""
    try:
        chunker = TextChunker(chunk_size=request.chunk_size, chunk_overlap=request.chunk_overlap)
        chunks = chunker.chunk(request.text, request.doc_id, request.metadata)
        return chunks
    except Exception as e:
        logger.error(f"Chunking error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/embed", response_model=EmbedResult)
async def embed_texts(request: EmbedRequest):
    """Generate embeddings for texts"""
    try:
        service = EmbeddingService()
        embeddings = service.embed(request.texts)
        return {
            "embeddings": embeddings,
            "model": service.model_name,
            "dimension": len(embeddings[0]) if embeddings else 0,
        }
    except Exception as e:
        logger.error(f"Embedding error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cluster", response_model=ClusterResult)
async def cluster_embeddings(request: ClusterRequest):
    """Cluster embeddings with auto-K or forced K"""
    try:
        service = ClusteringService()
        result = service.cluster(
            request.embeddings,
            method=request.method,
            force_k=request.force_k,
            k_range=request.k_range
        )
        return result
    except Exception as e:
        logger.error(f"Clustering error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/pipeline")
async def run_pipeline(request: PipelineRequest, background_tasks: BackgroundTasks):
    """Async pipeline: chunk → embed → cluster (returns job_id)"""
    job_id = str(uuid4())
    _jobs[job_id] = {"status": "pending", "progress": 0, "current_step": "queued"}

    background_tasks.add_task(_execute_pipeline, job_id, request)

    return {"job_id": job_id, "status": "pending"}


@router.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Get status of an async job"""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, **job}


# ── Background Pipeline ──

async def _execute_pipeline(job_id: str, request: PipelineRequest):
    """Execute the full intelligence pipeline in background"""
    try:
        _jobs[job_id] = {"status": "running", "progress": 0, "current_step": "chunking"}

        # Step 1: Chunk all documents
        chunker = TextChunker(chunk_size=request.chunk_size, chunk_overlap=request.chunk_overlap)
        all_chunks = []
        for doc in request.texts:
            chunks = chunker.chunk(doc["text"], doc["doc_id"], doc.get("metadata", {}))
            all_chunks.extend(chunks)

        _jobs[job_id]["progress"] = 30
        _jobs[job_id]["current_step"] = "embedding"

        # Step 2: Generate embeddings
        embedder = EmbeddingService()
        texts = [c["text"] for c in all_chunks]
        embeddings = embedder.embed(texts)

        _jobs[job_id]["progress"] = 60
        _jobs[job_id]["current_step"] = "clustering"

        # Step 3: Cluster
        clusterer = ClusteringService()
        cluster_result = clusterer.cluster(embeddings, method=request.clustering_method)

        # Attach cluster labels to chunks
        for i, chunk in enumerate(all_chunks):
            chunk["cluster_id"] = cluster_result["labels"][i]
            chunk["embedding"] = embeddings[i]

        _jobs[job_id] = {
            "status": "completed",
            "progress": 100,
            "current_step": "done",
            "result": {
                "total_chunks": len(all_chunks),
                "n_clusters": cluster_result["n_clusters"],
                "silhouette_score": cluster_result["silhouette_score"],
                "chunks": all_chunks,  # Full results
            }
        }

    except Exception as e:
        logger.error(f"Pipeline error for job {job_id}: {e}")
        _jobs[job_id] = {
            "status": "failed",
            "progress": _jobs[job_id].get("progress", 0),
            "current_step": "error",
            "error": str(e)
        }
