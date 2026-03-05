# services/service_c/app/api/external_api.py
"""
External API v1 — For agentic systems (LangChain, LlamaIndex, custom agents)
Auth: API Key in header X-API-Key
Exposes: search, chunks, relations, graph traversal
"""

import os
from fastapi import APIRouter, HTTPException, Depends, Header, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import httpx
import logging

from shared.config.database import get_db
from shared.models.orm import Owner, Project, Chunk, Relation, Document

router = APIRouter()
logger = logging.getLogger("service-c.external-api")

STORAGE_URL = os.getenv("STORAGE_SERVICE_URL", "http://service-a:8000")
INTELLIGENCE_URL = os.getenv("INTELLIGENCE_SERVICE_URL", "http://service-b:8001")
LLM_URL = os.getenv("LLM_URL", "http://host.docker.internal:1234/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")


# ── API Key Auth ──

async def get_api_user(
    x_api_key: str = Header(..., description="API key from user profile"),
    db: AsyncSession = Depends(get_db)
) -> Owner:
    """Authenticate via API key (for external/agentic systems)"""
    if not x_api_key or not x_api_key.startswith("gr_"):
        raise HTTPException(status_code=401, detail="Invalid API key format")

    result = await db.execute(select(Owner).where(Owner.api_key == x_api_key))
    owner = result.scalar_one_or_none()
    if not owner or not owner.is_active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")

    return owner


# ── Models ──

class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    project_id: str
    n_results: int = Field(default=10, ge=1, le=100)
    filters: Optional[Dict[str, Any]] = None

class SearchResult(BaseModel):
    chunk_id: str
    text: str
    score: float
    metadata: Dict[str, Any]

class GraphNeighborsRequest(BaseModel):
    chunk_id: str
    project_id: str
    relation_types: Optional[List[str]] = None
    max_hops: int = Field(default=10, ge=1, le=20)
    budget: float = Field(default=1.0, ge=0.1, le=5.0)
    min_similarity: float = Field(default=0.1, ge=0.0, le=1.0)
    mode: str = Field(default="auto", pattern="^(auto|fixed)$")  # "auto" = budget-based, "fixed" = legacy BFS


# ── Endpoints ──

@router.get("/projects")
async def list_projects(
    owner: Owner = Depends(get_api_user),
    db: AsyncSession = Depends(get_db)
):
    """List all projects accessible by this API key"""
    result = await db.execute(
        select(Project)
        .where(Project.owner_id == owner.id, Project.status != "deleted")
    )
    projects = result.scalars().all()

    return {
        "projects": [
            {
                "id": str(p.id),
                "name": p.name,
                "total_documents": p.total_documents,
                "total_chunks": p.total_chunks,
                "total_relations": p.total_relations,
                "status": p.status,
            }
            for p in projects
        ]
    }


@router.post("/search", response_model=List[SearchResult])
async def semantic_search(
    request: SearchRequest,
    owner: Owner = Depends(get_api_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Semantic search within a project.
    For agentic systems: send a natural language query, get ranked chunks.
    """
    # Verify project access
    result = await db.execute(
        select(Project).where(Project.id == request.project_id, Project.owner_id == owner.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Step 1: Embed the query via Service B
    async with httpx.AsyncClient(timeout=30) as client:
        embed_resp = await client.post(
            f"{INTELLIGENCE_URL}/intelligence/embed",
            json={"texts": [request.query]}
        )
        if embed_resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Embedding service error")

        query_embedding = embed_resp.json()["embeddings"][0]

    # Step 2: Search via Service A
    async with httpx.AsyncClient(timeout=30) as client:
        search_resp = await client.post(
            f"{STORAGE_URL}/storage/projects/{owner.id}/{project.id}/search",
            json={
                "owner_id": str(owner.id),
                "project_id": str(project.id),
                "query_embedding": query_embedding,
                "n_results": request.n_results,
                "where_filter": request.filters,
            }
        )
        if search_resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Storage service error")

    return search_resp.json()


@router.get("/projects/{project_id}/chunks")
async def list_chunks(
    project_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    cluster_id: Optional[int] = None,
    owner: Owner = Depends(get_api_user),
    db: AsyncSession = Depends(get_db)
):
    """List chunks in a project (for graph exploration by agents)"""
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == owner.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    async with httpx.AsyncClient(timeout=30) as client:
        params = {"offset": offset, "limit": limit}
        if cluster_id is not None:
            params["cluster_id"] = cluster_id

        resp = await client.get(
            f"{STORAGE_URL}/storage/projects/{owner.id}/{project_id}/chunks",
            params=params
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Storage service error")

    return resp.json()


@router.get("/projects/{project_id}/chunks/{chunk_id}")
async def get_chunk(
    project_id: str,
    chunk_id: str,
    owner: Owner = Depends(get_api_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific chunk with full content"""
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == owner.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{STORAGE_URL}/storage/projects/{owner.id}/{project_id}/chunks/{chunk_id}"
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Chunk not found")

    return resp.json()


@router.get("/projects/{project_id}/relations")
async def get_relations(
    project_id: str,
    chunk_id: Optional[str] = None,
    relation_type: Optional[str] = None,
    min_confidence: float = Query(0.0, ge=0, le=1),
    limit: int = Query(50, ge=1, le=500),
    owner: Owner = Depends(get_api_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get relations for a project. Optionally filter by chunk, type, confidence.
    For agentic graph navigation.
    """
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == owner.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    # Query relations from PostgreSQL
    query = select(Relation).where(Relation.project_id == project_id)

    if chunk_id:
        query = query.where(
            (Relation.chunk_a_id == chunk_id) | (Relation.chunk_b_id == chunk_id)
        )
    if relation_type:
        query = query.where(Relation.type == relation_type)

    query = query.where(Relation.confiance >= min_confidence)
    query = query.limit(limit)

    result = await db.execute(query)
    relations = result.scalars().all()

    return {
        "relations": [
            {
                "id": str(r.id),
                "chunk_a_id": str(r.chunk_a_id),
                "chunk_b_id": str(r.chunk_b_id),
                "type": r.type,
                "intensite": r.intensite,
                "confiance": r.confiance,
                "similarite_cosinus": r.similarite_cosinus,
                "justification": r.justification,
            }
            for r in relations
        ],
        "total": len(relations),
    }


@router.get("/projects/{project_id}/stats")
async def get_project_stats(
    project_id: str,
    owner: Owner = Depends(get_api_user),
    db: AsyncSession = Depends(get_db)
):
    """Get project statistics (for agentic context sizing)"""
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == owner.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return {
        "project_id": str(project.id),
        "name": project.name,
        "total_documents": project.total_documents,
        "total_chunks": project.total_chunks,
        "total_relations": project.total_relations,
        "embedding_model": project.embedding_model,
        "chunking_size": project.chunking_size,
        "chunking_overlap": project.chunking_overlap,
        "status": project.status,
    }


# ══════════════════════════════════════
# CHAT GRAPH-RAG (for agents)
# ══════════════════════════════════════

class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=5000)
    project_id: str
    n_context: int = Field(default=5, ge=1, le=20)
    use_graph: bool = True
    temperature: float = Field(default=0.3, ge=0.0, le=1.0)
    system_prompt: Optional[str] = None  # Custom system prompt for agents


@router.post("/chat")
async def chat_graphrag(
    request: ChatRequest,
    owner: Owner = Depends(get_api_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Graph-RAG Chat endpoint for agents.
    Pipeline: question → embed → semantic search → graph enrichment → LLM → answer with sources.
    
    Agents can provide a custom system_prompt to control the LLM behavior.
    """
    # Verify project access
    result = await db.execute(
        select(Project).where(Project.id == request.project_id, Project.owner_id == owner.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Step 1: Embed the question
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{INTELLIGENCE_URL}/intelligence/embed",
            json={"texts": [request.question]}
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Embedding service error")
        query_embedding = resp.json()["embeddings"][0]

    # Step 2: Semantic search
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{STORAGE_URL}/storage/projects/{owner.id}/{request.project_id}/search",
            json={
                "owner_id": str(owner.id),
                "project_id": str(request.project_id),
                "query_embedding": query_embedding,
                "n_results": request.n_context,
            }
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail="Storage service error")
        search_results = resp.json()

    # Step 3: Build context with graph enrichment
    context_chunks = []
    sources = []
    seen_texts = set()

    for sr in search_results:
        text = sr.get("text", "")
        if text and text not in seen_texts:
            context_chunks.append(text)
            seen_texts.add(text)

            chromadb_id = sr["chunk_id"]
            doc_title = sr.get("metadata", {}).get("title", "")

            # Get chunk from PostgreSQL for graph enrichment
            chunk_result = await db.execute(
                select(Chunk).where(Chunk.chromadb_id == chromadb_id)
            )
            chunk = chunk_result.scalar_one_or_none()
            if chunk:
                doc_result = await db.execute(select(Document).where(Document.id == chunk.document_id))
                doc = doc_result.scalar_one_or_none()
                if doc:
                    doc_title = doc.title or doc_title

            sources.append({
                "chunk_id": chromadb_id,
                "doc_title": doc_title,
                "score": sr.get("score", 0),
                "text_preview": text[:200],
            })

            # Graph enrichment: 1-hop neighbors
            if request.use_graph and chunk:
                rels_result = await db.execute(
                    select(Relation).where(
                        (Relation.chunk_a_id == chunk.id) | (Relation.chunk_b_id == chunk.id),
                        Relation.confiance >= 0.6,
                    ).order_by(Relation.confiance.desc()).limit(3)
                )
                for r in rels_result.scalars().all():
                    neighbor_id = r.chunk_b_id if str(r.chunk_a_id) == str(chunk.id) else r.chunk_a_id
                    neighbor_result = await db.execute(select(Chunk).where(Chunk.id == neighbor_id))
                    neighbor = neighbor_result.scalar_one_or_none()
                    if neighbor and neighbor.chromadb_id:
                        try:
                            async with httpx.AsyncClient(timeout=10) as client2:
                                chunk_resp = await client2.get(
                                    f"{STORAGE_URL}/storage/projects/{owner.id}/{request.project_id}/chunks/{neighbor.chromadb_id}"
                                )
                                if chunk_resp.status_code == 200:
                                    n_text = chunk_resp.json().get("text", "")
                                    if n_text and n_text not in seen_texts:
                                        context_chunks.append(f"[Relation {r.type}]\n{n_text}")
                                        seen_texts.add(n_text)
                        except Exception:
                            pass

    # Step 4: Build LLM prompt
    context_text = "\n\n---\n\n".join(context_chunks[:15])

    system = request.system_prompt or (
        f"Tu es un assistant expert qui répond aux questions en se basant UNIQUEMENT sur le contexte fourni.\n"
        f"Si le contexte ne contient pas assez d'informations, dis-le clairement.\n"
        f"Réponds en français de manière structurée et précise.\n\n"
        f"CONTEXTE (corpus \"{project.name}\"):\n\n{context_text}"
    )

    if request.system_prompt:
        system = f"{request.system_prompt}\n\nCONTEXTE:\n\n{context_text}"

    # Step 5: Call LLM
    try:
        from openai import OpenAI
        llm_client = OpenAI(base_url=LLM_URL, api_key="lm-studio")

        response = llm_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": request.question},
            ],
            temperature=request.temperature,
            max_tokens=1500,
        )
        answer = response.choices[0].message.content.strip()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {str(e)[:200]}")

    return {
        "question": request.question,
        "answer": answer,
        "sources": sources,
        "context_chunks": len(context_chunks),
        "graph_enriched": request.use_graph,
        "model": LLM_MODEL,
    }


# ══════════════════════════════════════
# GRAPH TRAVERSAL (for agents)
# ══════════════════════════════════════

@router.post("/graph/neighbors")
async def get_graph_neighbors(
    request: GraphNeighborsRequest,
    owner: Owner = Depends(get_api_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Graph traversal: get neighbors of a chunk.

    Two modes:
    - "auto" (default): Budget-based best-first traversal using cosine similarity.
      High-similarity relations cost less, allowing deeper traversal.
      Budget starts at 1.0, each hop costs (1 - cosine_similarity).
    - "fixed": Legacy BFS traversal up to max_hops (ignores budget).
    """
    # Verify project access
    result = await db.execute(
        select(Project).where(Project.id == request.project_id, Project.owner_id == owner.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    # Find the starting chunk
    chunk_result = await db.execute(
        select(Chunk).where(
            Chunk.id == request.chunk_id,
            Chunk.project_id == request.project_id,
        )
    )
    start_chunk = chunk_result.scalar_one_or_none()

    # Also try by chromadb_id
    if not start_chunk:
        chunk_result = await db.execute(
            select(Chunk).where(
                Chunk.chromadb_id == request.chunk_id,
                Chunk.project_id == request.project_id,
            )
        )
        start_chunk = chunk_result.scalar_one_or_none()

    if not start_chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")

    start_id = str(start_chunk.id)

    if request.mode == "auto":
        # ── Auto-Hop: budget-based best-first traversal ──
        from shared.utils.auto_hop import auto_hop_traversal

        hop_result = await auto_hop_traversal(
            db=db,
            start_chunk_id=start_id,
            project_id=request.project_id,
            budget=request.budget,
            max_hops=request.max_hops,
            min_similarity=request.min_similarity,
            relation_types=request.relation_types,
        )

        return {
            "start_chunk_id": hop_result.start_chunk_id,
            "mode": "auto",
            "neighbors": [
                {
                    "chunk_id": n.chunk_id,
                    "chromadb_id": n.chromadb_id,
                    "cluster_id": n.cluster_id,
                    "doc_title": n.doc_title,
                    "hop": n.hop,
                    "budget_remaining": round(n.budget_remaining, 4),
                    "relation_type": n.relation_type,
                    "relation_similarity": round(n.relation_similarity, 4),
                    "relation_justification": n.relation_justification,
                }
                for n in hop_result.neighbors
            ],
            "total_neighbors": len(hop_result.neighbors),
            "total_hops": hop_result.total_hops,
            "budget_initial": hop_result.budget_initial,
            "budget_used": round(hop_result.budget_used, 4),
            "stopped_reason": hop_result.stopped_reason,
            "max_hops": hop_result.max_hops,
        }

    else:
        # ── Fixed mode: legacy BFS traversal ──
        visited = set()
        visited.add(start_id)
        current_frontier = {start_id}
        all_relations = []
        neighbor_chunks = []

        for hop in range(request.max_hops):
            if not current_frontier:
                break

            next_frontier = set()
            for chunk_id in current_frontier:
                # Get relations for this chunk
                query = select(Relation).where(
                    (Relation.chunk_a_id == chunk_id) | (Relation.chunk_b_id == chunk_id)
                )
                if request.relation_types:
                    query = query.where(Relation.type.in_(request.relation_types))

                rels_result = await db.execute(query)
                for r in rels_result.scalars().all():
                    neighbor_id = str(r.chunk_b_id) if str(r.chunk_a_id) == chunk_id else str(r.chunk_a_id)

                    all_relations.append({
                        "id": str(r.id),
                        "source": str(r.chunk_a_id),
                        "target": str(r.chunk_b_id),
                        "type": r.type,
                        "intensite": r.intensite,
                        "confiance": r.confiance,
                        "justification": r.justification,
                        "hop": hop + 1,
                    })

                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        next_frontier.add(neighbor_id)

                        # Fetch neighbor chunk info
                        n_result = await db.execute(select(Chunk).where(Chunk.id == neighbor_id))
                        n_chunk = n_result.scalar_one_or_none()
                        if n_chunk:
                            doc_result = await db.execute(select(Document).where(Document.id == n_chunk.document_id))
                            doc = doc_result.scalar_one_or_none()
                            neighbor_chunks.append({
                                "chunk_id": str(n_chunk.id),
                                "chromadb_id": n_chunk.chromadb_id,
                                "cluster_id": n_chunk.cluster_id,
                                "doc_title": doc.title if doc else "",
                                "doc_category": doc.category if doc else "",
                                "hop": hop + 1,
                            })

            current_frontier = next_frontier

        return {
            "start_chunk_id": start_id,
            "mode": "fixed",
            "neighbors": neighbor_chunks,
            "relations": all_relations,
            "total_neighbors": len(neighbor_chunks),
            "total_relations": len(all_relations),
            "max_hops": request.max_hops,
        }


# ══════════════════════════════════════
# CLUSTERS (for agents)
# ══════════════════════════════════════

@router.get("/projects/{project_id}/clusters")
async def list_clusters(
    project_id: str,
    owner: Owner = Depends(get_api_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all clusters in a project with chunk counts.
    For agentic topic discovery and navigation.
    """
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == owner.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    # Get cluster stats
    clusters_result = await db.execute(
        select(
            Chunk.cluster_id,
            func.count(Chunk.id).label("chunk_count"),
        )
        .where(Chunk.project_id == project_id, Chunk.cluster_id.isnot(None))
        .group_by(Chunk.cluster_id)
        .order_by(Chunk.cluster_id)
    )

    clusters = []
    for row in clusters_result:
        cluster_id = row[0]
        chunk_count = row[1]

        # Get sample doc titles for this cluster
        sample_result = await db.execute(
            select(Chunk, Document)
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.project_id == project_id, Chunk.cluster_id == cluster_id)
            .limit(5)
        )
        sample_titles = list(set(
            doc.title for chunk, doc in sample_result if doc.title
        ))

        clusters.append({
            "cluster_id": cluster_id,
            "chunk_count": chunk_count,
            "sample_doc_titles": sample_titles[:5],
        })

    return {
        "total_clusters": len(clusters),
        "clusters": clusters,
    }


# ══════════════════════════════════════
# GRAPH FULL DATA (for agents/viz)
# ══════════════════════════════════════

@router.get("/projects/{project_id}/graph")
async def get_graph_data(
    project_id: str,
    cluster_id: Optional[int] = None,
    relation_type: Optional[str] = None,
    min_confidence: float = Query(0.0, ge=0, le=1),
    limit_relations: int = Query(500, ge=1, le=5000),
    owner: Owner = Depends(get_api_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get full graph data (nodes + edges) for visualization or analysis.
    Optionally filter by cluster, relation type, or minimum confidence.
    """
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == owner.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    # Get relations
    query = select(Relation).where(
        Relation.project_id == project_id,
        Relation.confiance >= min_confidence,
    )
    if relation_type:
        query = query.where(Relation.type == relation_type)
    query = query.limit(limit_relations)

    rels_result = await db.execute(query)
    relations = rels_result.scalars().all()

    # Collect involved chunk IDs
    chunk_ids = set()
    edges = []
    for r in relations:
        chunk_ids.add(str(r.chunk_a_id))
        chunk_ids.add(str(r.chunk_b_id))
        edges.append({
            "source": str(r.chunk_a_id),
            "target": str(r.chunk_b_id),
            "type": r.type,
            "intensite": r.intensite,
            "confiance": r.confiance,
        })

    # Get nodes
    nodes = []
    if chunk_ids:
        chunks_result = await db.execute(
            select(Chunk, Document)
            .join(Document, Chunk.document_id == Document.id, isouter=True)
            .where(Chunk.id.in_(list(chunk_ids)))
        )
        for chunk, doc in chunks_result:
            if cluster_id is not None and chunk.cluster_id != cluster_id:
                continue
            nodes.append({
                "id": str(chunk.id),
                "chromadb_id": chunk.chromadb_id,
                "cluster_id": chunk.cluster_id,
                "doc_title": doc.title if doc else "",
                "doc_category": doc.category if doc else "",
                "relation_count": chunk.relation_count or 0,
            })

    return {
        "nodes": nodes,
        "edges": edges,
        "total_nodes": len(nodes),
        "total_edges": len(edges),
    }