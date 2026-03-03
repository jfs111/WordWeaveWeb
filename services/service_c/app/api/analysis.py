# services/service_c/app/api/analysis.py
"""Analysis API — Orchestrates clustering + relation detection across Service A + B"""

import os
from datetime import datetime, timezone
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func
from typing import List, Optional
import httpx
import logging

from shared.config.database import get_db
from shared.models.orm import Owner, Project, Document, Chunk, Relation, Job
from app.api.auth import get_current_user

router = APIRouter()
logger = logging.getLogger("service-c.analysis")

STORAGE_URL = os.getenv("STORAGE_SERVICE_URL", "http://service-a:8000")
INTELLIGENCE_URL = os.getenv("INTELLIGENCE_SERVICE_URL", "http://service-b:8001")


# ── Project Stats ──

@router.get("/{project_id}/stats")
async def get_project_stats(
    project_id: str,
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get full project statistics"""
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Count documents
    doc_result = await db.execute(
        select(func.count(Document.id)).where(Document.project_id == project_id, Document.status == 'processed')
    )
    n_docs = doc_result.scalar() or 0

    # Count chunks
    chunk_result = await db.execute(
        select(func.count(Chunk.id)).where(Chunk.project_id == project_id)
    )
    n_chunks = chunk_result.scalar() or 0

    # Count clusters
    cluster_result = await db.execute(
        select(func.count(func.distinct(Chunk.cluster_id)))
        .where(Chunk.project_id == project_id, Chunk.cluster_id.isnot(None))
    )
    n_clusters = cluster_result.scalar() or 0

    # Count relations
    rel_result = await db.execute(
        select(func.count(Relation.id)).where(Relation.project_id == project_id)
    )
    n_relations = rel_result.scalar() or 0

    return {
        "project_id": str(project.id),
        "name": project.name,
        "total_documents": n_docs,
        "total_chunks": n_chunks,
        "total_clusters": n_clusters,
        "total_relations": n_relations,
        "clustering_method": project.clustering_method,
        "similarity_threshold": project.similarity_threshold,
        "status": project.status,
    }


# ── LLM Status ──

@router.get("/{project_id}/llm-status")
async def check_llm_status(
    project_id: str,
    current_user: Owner = Depends(get_current_user),
):
    """Check if LLM service (LM Studio) is reachable"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{INTELLIGENCE_URL}/intelligence/llm-status")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        return {"connected": False, "error": str(e)}


# ── Cluster Project ──

@router.post("/{project_id}/cluster")
async def cluster_project(
    project_id: str,
    background_tasks: BackgroundTasks,
    force_k: Optional[int] = None,
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Launch clustering pipeline for the project"""
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Create job
    job = Job(
        project_id=project.id,
        owner_id=current_user.id,
        type="cluster",
        status="pending",
        input_data={"force_k": force_k},
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    background_tasks.add_task(
        _run_clustering_pipeline,
        str(project.id),
        str(current_user.id),
        str(job.id),
        project.clustering_method,
        force_k,
    )

    return {
        "job_id": str(job.id),
        "status": "pending",
        "message": "Clustering pipeline started",
    }


# ── Detect Relations ──

@router.post("/{project_id}/detect-relations")
async def detect_relations(
    project_id: str,
    background_tasks: BackgroundTasks,
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Launch relation detection pipeline (cluster-by-cluster with LLM)"""
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check that clustering was done
    cluster_check = await db.execute(
        select(func.count(Chunk.id))
        .where(Chunk.project_id == project_id, Chunk.cluster_id.isnot(None))
    )
    n_clustered = cluster_check.scalar() or 0
    if n_clustered == 0:
        raise HTTPException(
            status_code=400,
            detail="No clustered chunks found. Run clustering first."
        )

    # Create job
    job = Job(
        project_id=project.id,
        owner_id=current_user.id,
        type="relations",
        status="pending",
        input_data={"similarity_threshold": project.similarity_threshold},
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    background_tasks.add_task(
        _run_relations_pipeline,
        str(project.id),
        str(current_user.id),
        str(job.id),
        project.similarity_threshold,
    )

    return {
        "job_id": str(job.id),
        "status": "pending",
        "message": "Relation detection pipeline started",
    }


# ── Full Analysis (Cluster + Relations) ──

@router.post("/{project_id}/analyze")
async def full_analysis(
    project_id: str,
    background_tasks: BackgroundTasks,
    force_k: Optional[int] = None,
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Launch full analysis: clustering → relation detection"""
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Create job
    job = Job(
        project_id=project.id,
        owner_id=current_user.id,
        type="full_pipeline",
        status="pending",
        input_data={
            "force_k": force_k,
            "similarity_threshold": project.similarity_threshold,
        },
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    background_tasks.add_task(
        _run_full_analysis,
        str(project.id),
        str(current_user.id),
        str(job.id),
        project.clustering_method,
        force_k,
        project.similarity_threshold,
    )

    return {
        "job_id": str(job.id),
        "status": "pending",
        "message": "Full analysis pipeline started (clustering → relations)",
    }


# ── Graph Data ──

@router.get("/{project_id}/graph")
async def get_graph_data(
    project_id: str,
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get graph data for D3.js visualization (nodes + edges)"""
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    # Get chunks as nodes
    chunks_result = await db.execute(
        select(Chunk).where(Chunk.project_id == project_id).order_by(Chunk.created_at)
    )
    chunks = chunks_result.scalars().all()

    # Get document info for each chunk
    doc_ids = list(set(str(c.document_id) for c in chunks))
    docs_result = await db.execute(
        select(Document).where(Document.id.in_(doc_ids))
    )
    docs_map = {str(d.id): d for d in docs_result.scalars().all()}

    # Build nodes
    nodes = []
    chunk_id_to_idx = {}
    for i, chunk in enumerate(chunks):
        doc = docs_map.get(str(chunk.document_id))
        chunk_id_to_idx[str(chunk.id)] = i
        nodes.append({
            "id": str(chunk.id),
            "chromadb_id": chunk.chromadb_id,
            "label": chunk.text_preview[:80] if chunk.text_preview else f"Chunk {chunk.chunk_index}",
            "cluster_id": chunk.cluster_id,
            "document_id": str(chunk.document_id),
            "doc_title": doc.title if doc else "",
            "doc_category": doc.category if doc else "",
            "word_count": chunk.word_count,
            "relation_count": chunk.relation_count,
        })

    # Get relations as edges
    rels_result = await db.execute(
        select(Relation).where(Relation.project_id == project_id)
    )
    relations = rels_result.scalars().all()

    edges = []
    for rel in relations:
        source_idx = chunk_id_to_idx.get(str(rel.chunk_a_id))
        target_idx = chunk_id_to_idx.get(str(rel.chunk_b_id))
        if source_idx is not None and target_idx is not None:
            edges.append({
                "id": str(rel.id),
                "source": str(rel.chunk_a_id),
                "target": str(rel.chunk_b_id),
                "type": rel.type,
                "intensite": rel.intensite,
                "confiance": rel.confiance,
                "similarite_cosinus": rel.similarite_cosinus,
                "justification": rel.justification,
            })

    # Cluster summary
    cluster_summary = defaultdict(lambda: {"count": 0, "docs": set()})
    for chunk in chunks:
        if chunk.cluster_id is not None:
            cid = chunk.cluster_id
            cluster_summary[cid]["count"] += 1
            doc = docs_map.get(str(chunk.document_id))
            if doc and doc.title:
                cluster_summary[cid]["docs"].add(doc.title)

    clusters = [
        {
            "cluster_id": k,
            "size": v["count"],
            "documents": list(v["docs"])[:5],  # Top 5 doc titles
        }
        for k, v in sorted(cluster_summary.items())
    ]

    return {
        "nodes": nodes,
        "edges": edges,
        "clusters": clusters,
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "total_clusters": len(clusters),
    }


# ═══════════════════════════════════════════
# BACKGROUND PIPELINES
# ═══════════════════════════════════════════

async def _run_clustering_pipeline(
    project_id: str,
    owner_id: str,
    job_id: str,
    method: str,
    force_k: Optional[int],
):
    """Background: fetch embeddings from Service A → cluster via Service B → update DB"""
    from shared.config.database import async_session

    async with async_session() as db:
        try:
            await _update_job(db, job_id, "running", 0, "fetching_embeddings")

            # Step 1: Get all embeddings from ChromaDB via Service A
            logger.info(f"[Cluster {job_id}] Fetching embeddings from Service A...")
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.get(
                    f"{STORAGE_URL}/storage/projects/{owner_id}/{project_id}/embeddings"
                )
                resp.raise_for_status()
                data = resp.json()

            chunk_ids = data["chunk_ids"]
            embeddings = data["embeddings"]
            metadatas = data["metadatas"]
            n = data["total"]

            if n == 0:
                raise ValueError("No embeddings found. Upload documents first.")

            logger.info(f"[Cluster {job_id}] Got {n} embeddings")
            await _update_job(db, job_id, "running", 30, "clustering")

            # Step 2: Cluster via Service B
            logger.info(f"[Cluster {job_id}] Sending to Service B for clustering...")
            async with httpx.AsyncClient(timeout=600) as client:
                resp = await client.post(
                    f"{INTELLIGENCE_URL}/intelligence/cluster-project",
                    json={
                        "chunk_ids": chunk_ids,
                        "embeddings": embeddings,
                        "metadatas": metadatas,
                        "method": method,
                        "force_k": force_k,
                    },
                )
                resp.raise_for_status()
                cluster_data = resp.json()

            n_clusters = cluster_data["n_clusters"]
            sil_score = cluster_data["silhouette_score"]
            chunk_cluster_map = cluster_data["chunk_cluster_map"]

            logger.info(f"[Cluster {job_id}] K={n_clusters}, silhouette={sil_score:.3f}")
            await _update_job(db, job_id, "running", 60, "updating_chromadb")

            # Step 3: Update cluster_id in ChromaDB
            logger.info(f"[Cluster {job_id}] Updating ChromaDB cluster metadata...")
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{STORAGE_URL}/storage/projects/{owner_id}/{project_id}/update-clusters",
                    json={"updates": chunk_cluster_map},
                )
                resp.raise_for_status()

            await _update_job(db, job_id, "running", 80, "updating_postgresql")

            # Step 4: Update PostgreSQL chunks.cluster_id
            logger.info(f"[Cluster {job_id}] Updating PostgreSQL...")
            chromadb_to_cluster = {
                m["chunk_id"]: m["cluster_id"] for m in chunk_cluster_map
            }

            # Get all chunks for this project
            chunks_result = await db.execute(
                select(Chunk).where(Chunk.project_id == project_id)
            )
            chunks = chunks_result.scalars().all()

            updated_count = 0
            for chunk in chunks:
                if chunk.chromadb_id and chunk.chromadb_id in chromadb_to_cluster:
                    cluster_id = chromadb_to_cluster[chunk.chromadb_id]
                    await db.execute(
                        update(Chunk)
                        .where(Chunk.id == chunk.id)
                        .values(cluster_id=cluster_id)
                    )
                    updated_count += 1

            await db.commit()
            logger.info(f"[Cluster {job_id}] Updated {updated_count} chunks in PostgreSQL")

            # Done
            await _update_job(db, job_id, "completed", 100, "done")
            await db.execute(
                update(Job).where(Job.id == job_id).values(
                    output_data={
                        "n_clusters": n_clusters,
                        "silhouette_score": sil_score,
                        "davies_bouldin_score": cluster_data["davies_bouldin_score"],
                        "cluster_sizes": cluster_data["cluster_sizes"],
                        "chunks_updated": updated_count,
                    }
                )
            )
            await db.commit()

            logger.info(f"[Cluster {job_id}] ✅ Clustering completed: K={n_clusters}")

        except Exception as e:
            logger.error(f"[Cluster {job_id}] ❌ Error: {e}")
            await _update_job(db, job_id, "failed", None, "error", error=str(e))


async def _run_relations_pipeline(
    project_id: str,
    owner_id: str,
    job_id: str,
    similarity_threshold: float,
):
    """Background: iterate clusters → detect relations via Service B LLM → save to DB"""
    from shared.config.database import async_session

    async with async_session() as db:
        try:
            await _update_job(db, job_id, "running", 0, "loading_data")

            # Step 1: Get all embeddings + cluster info from Service A
            logger.info(f"[Relations {job_id}] Fetching embeddings...")
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.get(
                    f"{STORAGE_URL}/storage/projects/{owner_id}/{project_id}/embeddings"
                )
                resp.raise_for_status()
                data = resp.json()

            chunk_ids = data["chunk_ids"]
            embeddings = data["embeddings"]
            documents = data.get("documents", [])
            metadatas = data.get("metadatas", [])

            logger.info(f"[Relations {job_id}] Data: {len(chunk_ids)} ids, {len(embeddings)} emb, {len(documents)} docs, {len(metadatas)} metas")
            print(f"[Relations {job_id}] Data: {len(chunk_ids)} ids, {len(embeddings)} emb, {len(documents)} docs, {len(metadatas)} metas", flush=True)

            # Get cluster assignments from PostgreSQL
            chunks_result = await db.execute(
                select(Chunk).where(
                    Chunk.project_id == project_id,
                    Chunk.cluster_id.isnot(None)
                )
            )
            chunks = chunks_result.scalars().all()

            # Build chromadb_id → (cluster_id, chunk_uuid) map
            chromadb_to_info = {}
            for chunk in chunks:
                if chunk.chromadb_id:
                    chromadb_to_info[chunk.chromadb_id] = {
                        "cluster_id": chunk.cluster_id,
                        "chunk_uuid": str(chunk.id),
                    }

            # Group by cluster
            clusters = defaultdict(lambda: {"ids": [], "texts": [], "embeddings": [], "metas": [], "uuids": []})

            for i, cid in enumerate(chunk_ids):
                info = chromadb_to_info.get(cid)
                if info and i < len(embeddings):
                    cluster_id = info["cluster_id"]
                    clusters[cluster_id]["ids"].append(cid)
                    clusters[cluster_id]["texts"].append(documents[i] if i < len(documents) else "")
                    clusters[cluster_id]["embeddings"].append(embeddings[i])
                    clusters[cluster_id]["metas"].append(metadatas[i] if i < len(metadatas) else {})
                    clusters[cluster_id]["uuids"].append(info["chunk_uuid"])

            n_clusters = len(clusters)
            logger.info(f"[Relations {job_id}] {n_clusters} clusters to process")

            await _update_job(db, job_id, "running", 10, f"processing_clusters (0/{n_clusters})")

            # Step 2: Process each cluster
            total_relations = 0
            total_errors = 0

            # Delete existing relations for this project first
            await db.execute(
                Relation.__table__.delete().where(Relation.project_id == project_id)
            )
            # Reset chunk relation counts
            await db.execute(
                update(Chunk)
                .where(Chunk.project_id == project_id)
                .values(has_relations=False, relation_count=0)
            )
            await db.commit()

            for idx, (cluster_id, cluster_data) in enumerate(sorted(clusters.items())):
                progress = 10 + int((idx / n_clusters) * 80)
                await _update_job(
                    db, job_id, "running", progress,
                    f"cluster {cluster_id} ({idx+1}/{n_clusters})"
                )

                if len(cluster_data["ids"]) < 2:
                    continue

                # Call Service B for relation detection
                n_chunks_in_cluster = len(cluster_data["ids"])
                logger.info(f"[Relations {job_id}] Cluster {cluster_id}: {n_chunks_in_cluster} chunks, sending to Service B...")

                try:
                    # Timeout: 30s per chunk in cluster (LLM needs time)
                    cluster_timeout = max(600, n_chunks_in_cluster * 30)
                    async with httpx.AsyncClient(timeout=cluster_timeout) as client:
                        resp = await client.post(
                            f"{INTELLIGENCE_URL}/intelligence/detect-relations",
                            json={
                                "cluster_id": cluster_id,
                                "chunk_ids": cluster_data["ids"],
                                "texts": cluster_data["texts"],
                                "embeddings": cluster_data["embeddings"],
                                "metadatas": cluster_data["metas"],
                                "similarity_threshold": similarity_threshold,
                            },
                        )
                        resp.raise_for_status()
                        result = resp.json()

                except Exception as e:
                    logger.error(f"[Relations {job_id}] Cluster {cluster_id} error: {e}")
                    total_errors += 1
                    continue

                relations = result.get("relations", [])
                cluster_saved = 0

                # Save relations to PostgreSQL
                # Need to map chromadb_id → chunk UUID
                chromadb_to_uuid = dict(zip(cluster_data["ids"], cluster_data["uuids"]))

                for rel in relations:
                    uuid_a = chromadb_to_uuid.get(rel["chunk_a_id"])
                    uuid_b = chromadb_to_uuid.get(rel["chunk_b_id"])

                    if not uuid_a or not uuid_b:
                        continue

                    try:
                        relation = Relation(
                            project_id=project_id,
                            chunk_a_id=uuid_a,
                            chunk_b_id=uuid_b,
                            type=rel["type"],
                            intensite=rel["intensite"],
                            confiance=rel["confiance"],
                            similarite_cosinus=rel["similarite_cosinus"],
                            justification=rel["justification"],
                        )
                        db.add(relation)
                        cluster_saved += 1
                        total_relations += 1

                        # Update chunk relation counts
                        for uid in [uuid_a, uuid_b]:
                            await db.execute(
                                update(Chunk)
                                .where(Chunk.id == uid)
                                .values(
                                    has_relations=True,
                                    relation_count=Chunk.relation_count + 1,
                                )
                            )
                    except Exception as e:
                        logger.warning(f"[Relations {job_id}] Skip relation: {e}")
                        continue

                # Commit after each cluster + update project total
                await db.commit()
                await db.execute(
                    update(Project)
                    .where(Project.id == project_id)
                    .values(total_relations=total_relations)
                )
                await db.commit()
                logger.info(f"[Relations {job_id}] Cluster {cluster_id}: {cluster_saved} relations saved (total: {total_relations})")

            # Step 3: Update project stats
            await db.execute(
                update(Project)
                .where(Project.id == project_id)
                .values(total_relations=total_relations)
            )
            await db.commit()

            # Done
            await _update_job(db, job_id, "completed", 100, "done")
            await db.execute(
                update(Job).where(Job.id == job_id).values(
                    output_data={
                        "total_relations": total_relations,
                        "clusters_processed": n_clusters,
                        "errors": total_errors,
                    }
                )
            )
            await db.commit()

            logger.info(f"[Relations {job_id}] ✅ Done: {total_relations} relations across {n_clusters} clusters")

        except Exception as e:
            import traceback
            logger.error(f"[Relations {job_id}] ❌ Error: {e}", exc_info=True)
            print(f"[Relations {job_id}] ❌ Error: {e}", flush=True)
            print(traceback.format_exc(), flush=True)
            await _update_job(db, job_id, "failed", None, "error", error=str(e))


async def _run_full_analysis(
    project_id: str,
    owner_id: str,
    job_id: str,
    method: str,
    force_k: Optional[int],
    similarity_threshold: float,
):
    """Background: full pipeline = clustering → relation detection"""
    from shared.config.database import async_session

    async with async_session() as db:
        try:
            await _update_job(db, job_id, "running", 0, "starting_clustering")

            # Phase 1: Clustering
            logger.info(f"[FullAnalysis {job_id}] Phase 1: Clustering...")
            await _run_clustering_pipeline(project_id, owner_id, job_id, method, force_k)

            # Check if clustering succeeded
            job_result = await db.execute(select(Job).where(Job.id == job_id))
            job = job_result.scalar_one_or_none()
            if job and job.status == "failed":
                return  # Already marked as failed

            # Phase 2: Relations
            await _update_job(db, job_id, "running", 50, "starting_relations")
            logger.info(f"[FullAnalysis {job_id}] Phase 2: Relation detection...")
            await _run_relations_pipeline(project_id, owner_id, job_id, similarity_threshold)

        except Exception as e:
            logger.error(f"[FullAnalysis {job_id}] ❌ Error: {e}")
            await _update_job(db, job_id, "failed", None, "error", error=str(e))


# ── Helpers ──

async def _update_job(db, job_id, status, progress=None, step=None, error=None):
    values = {"status": status}
    if progress is not None:
        values["progress"] = progress
    if step:
        values["current_step"] = step
    if error:
        values["error_message"] = error
    if status == "running" and progress == 0:
        values["started_at"] = datetime.now(timezone.utc)
    if status in ("completed", "failed"):
        values["completed_at"] = datetime.now(timezone.utc)

    await db.execute(update(Job).where(Job.id == job_id).values(**values))
    await db.commit()