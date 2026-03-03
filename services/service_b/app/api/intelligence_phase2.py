# services/service_b/app/api/intelligence_phase2.py
"""Phase 2 Intelligence API — Project-level clustering + LLM relation detection"""

import os
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import logging

from app.services.clusterer import ClusteringService
from app.services.relation_detector import RelationDetector

router = APIRouter()
logger = logging.getLogger("service-b.intelligence-phase2")


# ── Request/Response Models ──

class ClusterProjectRequest(BaseModel):
    """Request to cluster all embeddings of a project"""
    chunk_ids: List[str]
    embeddings: List[List[float]]
    metadatas: List[Dict[str, Any]] = []
    method: str = "auto-k"
    force_k: Optional[int] = None


class ClusterProjectResponse(BaseModel):
    labels: List[int]
    n_clusters: int
    silhouette_score: float
    davies_bouldin_score: float
    chunk_cluster_map: List[Dict[str, Any]]  # [{chunk_id, cluster_id}, ...]
    cluster_sizes: Dict[str, int]  # {"0": 45, "1": 32, ...}


class DetectRelationsRequest(BaseModel):
    """Request to detect relations — sends one cluster's worth of data"""
    cluster_id: int
    chunk_ids: List[str]
    texts: List[str]
    embeddings: List[List[float]]
    metadatas: List[Dict[str, Any]] = []
    similarity_threshold: float = 0.6
    max_pairs: int = 500


class RelationResult(BaseModel):
    chunk_a_id: str
    chunk_b_id: str
    type: str
    intensite: str
    confiance: float
    similarite_cosinus: float
    justification: str


class DetectRelationsResponse(BaseModel):
    cluster_id: int
    relations: List[RelationResult]
    stats: Dict[str, Any]


class LLMStatusResponse(BaseModel):
    connected: bool
    url: str
    model: str
    error: Optional[str] = None


# ── Endpoints ──

@router.post("/cluster-project", response_model=ClusterProjectResponse)
async def cluster_project(request: ClusterProjectRequest):
    """
    Cluster all embeddings for a project.
    Uses auto-K algorithm (elbow + silhouette + Davies-Bouldin).
    Returns cluster assignments for each chunk.
    """
    try:
        n = len(request.embeddings)
        if n < 3:
            # Too few to cluster meaningfully
            labels = [0] * n
            return ClusterProjectResponse(
                labels=labels,
                n_clusters=1,
                silhouette_score=0.0,
                davies_bouldin_score=0.0,
                chunk_cluster_map=[
                    {"chunk_id": cid, "cluster_id": 0}
                    for cid in request.chunk_ids
                ],
                cluster_sizes={"0": n},
            )

        logger.info(f"Clustering {n} embeddings (method={request.method})...")

        clusterer = ClusteringService()
        result = clusterer.cluster(
            request.embeddings,
            method=request.method,
            force_k=request.force_k,
        )

        labels = result["labels"]

        # Build chunk→cluster map
        chunk_cluster_map = [
            {"chunk_id": request.chunk_ids[i], "cluster_id": labels[i]}
            for i in range(n)
        ]

        # Cluster sizes
        from collections import Counter
        sizes = Counter(labels)
        cluster_sizes = {str(k): v for k, v in sorted(sizes.items())}

        logger.info(
            f"Clustering done: K={result['n_clusters']}, "
            f"silhouette={result['silhouette_score']:.3f}, "
            f"sizes={dict(sizes.most_common(5))}..."
        )

        return ClusterProjectResponse(
            labels=labels,
            n_clusters=result["n_clusters"],
            silhouette_score=result["silhouette_score"],
            davies_bouldin_score=result["davies_bouldin_score"],
            chunk_cluster_map=chunk_cluster_map,
            cluster_sizes=cluster_sizes,
        )

    except Exception as e:
        logger.error(f"Clustering error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/detect-relations", response_model=DetectRelationsResponse)
async def detect_relations(request: DetectRelationsRequest):
    """
    Detect semantic relations within a single cluster using LLM.
    
    Pipeline:
    1. Pre-filter pairs by cosine similarity >= threshold
    2. Send filtered pairs to LLM (LM Studio)
    3. Parse and validate JSON responses
    4. Return relations
    """
    try:
        detector = RelationDetector(
            similarity_threshold=request.similarity_threshold,
            max_pairs_per_cluster=request.max_pairs,
        )

        relations = detector.detect_relations_for_cluster(
            cluster_id=request.cluster_id,
            chunk_ids=request.chunk_ids,
            texts=request.texts,
            embeddings=request.embeddings,
            metadatas=request.metadatas,
        )

        return DetectRelationsResponse(
            cluster_id=request.cluster_id,
            relations=relations,
            stats=detector.get_stats(),
        )

    except Exception as e:
        logger.error(f"Relation detection error for cluster {request.cluster_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm-status", response_model=LLMStatusResponse)
async def check_llm_status():
    """Check if LLM (LM Studio) is reachable"""
    url = os.getenv("LLM_URL", "http://host.docker.internal:1234/v1")
    model = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")

    detector = RelationDetector(llm_url=url, llm_model=model)
    try:
        connected = detector.test_connection()
        return LLMStatusResponse(
            connected=connected,
            url=url,
            model=model,
        )
    except Exception as e:
        return LLMStatusResponse(
            connected=False,
            url=url,
            model=model,
            error=str(e),
        )
