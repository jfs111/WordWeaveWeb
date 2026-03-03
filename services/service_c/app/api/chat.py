# services/service_c/app/api/chat.py
"""Chat Graph-RAG — Semantic search + Graph-enriched context + LLM response"""

import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx
import logging

from shared.config.database import get_db
from shared.models.orm import Owner, Project, Chunk, Relation
from app.api.auth import get_current_user

router = APIRouter()
logger = logging.getLogger("service-c.chat")

STORAGE_URL = os.getenv("STORAGE_SERVICE_URL", "http://service-a:8000")
INTELLIGENCE_URL = os.getenv("INTELLIGENCE_SERVICE_URL", "http://service-b:8001")
LLM_URL = os.getenv("LLM_URL", "http://host.docker.internal:1234/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")


# ── Models ──

class SearchQuery(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    n_results: int = Field(default=10, ge=1, le=50)
    use_graph: bool = True  # Enrich with graph relations
    max_hops: int = Field(default=1, ge=0, le=2)


class SearchResultItem(BaseModel):
    chunk_id: str
    chromadb_id: str
    text: str
    score: float
    doc_title: str
    doc_category: str
    cluster_id: Optional[int]
    relations: List[Dict[str, Any]] = []


class SearchResponse(BaseModel):
    query: str
    results: List[SearchResultItem]
    total: int
    graph_enriched: bool


class ChatQuery(BaseModel):
    question: str = Field(min_length=1, max_length=5000)
    n_context: int = Field(default=5, ge=1, le=20)
    use_graph: bool = True
    max_hops: int = Field(default=1, ge=0, le=2)
    temperature: float = Field(default=0.3, ge=0.0, le=1.0)


class ChatResponse(BaseModel):
    question: str
    answer: str
    sources: List[Dict[str, Any]]
    context_chunks: int
    graph_enriched: bool


# ── Semantic Search ──

@router.post("/{project_id}/search", response_model=SearchResponse)
async def semantic_search(
    project_id: str,
    request: SearchQuery,
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Semantic search within a project.
    Optionally enriches results with graph relations (connected chunks).
    """
    # Verify access
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Step 1: Embed the query
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{INTELLIGENCE_URL}/intelligence/embed",
            json={"texts": [request.query]}
        )
        resp.raise_for_status()
        query_embedding = resp.json()["embeddings"][0]

    # Step 2: Search ChromaDB via Service A
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{STORAGE_URL}/storage/projects/{current_user.id}/{project_id}/search",
            json={
                "owner_id": str(current_user.id),
                "project_id": str(project_id),
                "query_embedding": query_embedding,
                "n_results": request.n_results,
            }
        )
        resp.raise_for_status()
        search_results = resp.json()

    # Step 3: Enrich with PostgreSQL metadata + graph relations
    enriched = []
    for sr in search_results:
        chromadb_id = sr["chunk_id"]

        # Get chunk from PostgreSQL
        chunk_result = await db.execute(
            select(Chunk).where(Chunk.chromadb_id == chromadb_id)
        )
        chunk = chunk_result.scalar_one_or_none()

        doc_title = sr.get("metadata", {}).get("title", "")
        doc_category = sr.get("metadata", {}).get("category", "")
        cluster_id = None
        chunk_uuid = chromadb_id
        relations = []

        if chunk:
            cluster_id = chunk.cluster_id
            chunk_uuid = str(chunk.id)

            # Get document info
            from shared.models.orm import Document
            doc_result = await db.execute(
                select(Document).where(Document.id == chunk.document_id)
            )
            doc = doc_result.scalar_one_or_none()
            if doc:
                doc_title = doc.title or doc_title
                doc_category = doc.category or doc_category

            # Graph enrichment: get relations for this chunk
            if request.use_graph and chunk:
                rels_result = await db.execute(
                    select(Relation).where(
                        (Relation.chunk_a_id == chunk.id) | (Relation.chunk_b_id == chunk.id)
                    ).limit(10)
                )
                rels = rels_result.scalars().all()
                for r in rels:
                    relations.append({
                        "type": r.type,
                        "intensite": r.intensite,
                        "confiance": r.confiance,
                        "connected_chunk_id": str(r.chunk_b_id) if str(r.chunk_a_id) == str(chunk.id) else str(r.chunk_a_id),
                        "justification": r.justification,
                    })

        enriched.append(SearchResultItem(
            chunk_id=chunk_uuid,
            chromadb_id=chromadb_id,
            text=sr.get("text", ""),
            score=sr.get("score", 0),
            doc_title=doc_title,
            doc_category=doc_category,
            cluster_id=cluster_id,
            relations=relations,
        ))

    return SearchResponse(
        query=request.query,
        results=enriched,
        total=len(enriched),
        graph_enriched=request.use_graph,
    )


# ── Chat Graph-RAG ──

@router.post("/{project_id}/chat", response_model=ChatResponse)
async def chat_graphrag(
    project_id: str,
    request: ChatQuery,
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Graph-RAG Chat: question → semantic search → graph enrichment → LLM answer.

    Pipeline:
    1. Embed question
    2. Search top-N similar chunks
    3. If use_graph: fetch related chunks via graph relations
    4. Build enriched context
    5. Send to LLM with context
    6. Return answer + sources
    """
    # Verify access
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Step 1: Embed the question
    logger.info(f"[Chat] Question: {request.question[:80]}...")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{INTELLIGENCE_URL}/intelligence/embed",
            json={"texts": [request.question]}
        )
        resp.raise_for_status()
        query_embedding = resp.json()["embeddings"][0]

    # Step 2: Semantic search
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{STORAGE_URL}/storage/projects/{current_user.id}/{project_id}/search",
            json={
                "owner_id": str(current_user.id),
                "project_id": str(project_id),
                "query_embedding": query_embedding,
                "n_results": request.n_context,
            }
        )
        resp.raise_for_status()
        search_results = resp.json()

    # Step 3: Graph enrichment
    vector_chunks = []    # Direct vector results (always kept)
    graph_chunks = []     # Graph neighbors (added on top)
    sources = []
    seen_texts = set()

    for sr in search_results:
        text = sr.get("text", "")
        if text and text not in seen_texts:
            vector_chunks.append(text)
            seen_texts.add(text)

            # Get metadata
            chromadb_id = sr["chunk_id"]
            chunk_result = await db.execute(
                select(Chunk).where(Chunk.chromadb_id == chromadb_id)
            )
            chunk = chunk_result.scalar_one_or_none()

            doc_title = sr.get("metadata", {}).get("title", "")
            if chunk:
                from shared.models.orm import Document
                doc_result = await db.execute(
                    select(Document).where(Document.id == chunk.document_id)
                )
                doc = doc_result.scalar_one_or_none()
                if doc:
                    doc_title = doc.title or doc_title

            sources.append({
                "chunk_id": chromadb_id,
                "doc_title": doc_title,
                "score": sr.get("score", 0),
                "text_preview": text[:200],
            })

            # Graph: fetch related chunks (1-hop neighbors)
            if request.use_graph and chunk:
                rels_result = await db.execute(
                    select(Relation).where(
                        (Relation.chunk_a_id == chunk.id) | (Relation.chunk_b_id == chunk.id),
                        Relation.confiance >= 0.6,
                    ).order_by(Relation.confiance.desc()).limit(3)
                )
                rels = rels_result.scalars().all()

                for r in rels:
                    # Get the connected chunk
                    neighbor_id = r.chunk_b_id if str(r.chunk_a_id) == str(chunk.id) else r.chunk_a_id
                    neighbor_result = await db.execute(
                        select(Chunk).where(Chunk.id == neighbor_id)
                    )
                    neighbor = neighbor_result.scalar_one_or_none()
                    if neighbor and neighbor.chromadb_id:
                        # Fetch full text from ChromaDB
                        try:
                            async with httpx.AsyncClient(timeout=60) as client:
                                chunk_resp = await client.get(
                                    f"{STORAGE_URL}/storage/projects/{current_user.id}/{project_id}/chunks/{neighbor.chromadb_id}"
                                )
                                if chunk_resp.status_code == 200:
                                    neighbor_data = chunk_resp.json()
                                    neighbor_text = neighbor_data.get("text", "")
                                    if neighbor_text and neighbor_text not in seen_texts:
                                        # Add as graph-enriched context
                                        graph_chunks.append(
                                                                f"[Relation {r.type} — {r.justification or ''}]\n{neighbor_text}"
                                                            )
                                        seen_texts.add(neighbor_text)
                                        # Also add to sources for accurate count in UI
                                        n_doc_result = await db.execute(
                                            select(Document).where(Document.id == neighbor.document_id)
                                        )
                                        n_doc = n_doc_result.scalar_one_or_none()
                                        sources.append({
                                            "chunk_id": neighbor.chromadb_id,
                                            "doc_title": n_doc.title if n_doc else "",
                                            "score": r.confiance,
                                            "text_preview": neighbor_text[:200],
                                        })

                        except Exception:
                            pass  # Skip on error

    # Step 4: Build LLM prompt
    all_context = vector_chunks + graph_chunks[:20]
    context_text = "\n\n---\n\n".join(all_context)
    logger.info(f"[Chat] Context: {len(vector_chunks)} vector + {len(graph_chunks[:20])} graph = {len(all_context)} chunks")

    system_prompt = f"""Tu es un assistant expert qui répond aux questions en se basant UNIQUEMENT sur le contexte fourni.
Si le contexte ne contient pas assez d'informations pour répondre, dis-le clairement.
Réponds en français de manière structurée et précise.
Cite les sources pertinentes quand c'est possible.

CONTEXTE (extraits du corpus "{project.name}"):

{context_text}"""

    # Step 5: Call LLM
    logger.info(f"[Chat] Sending to LLM with {len(all_context)} context chunks...")

    try:
        from openai import OpenAI
        llm_client = OpenAI(base_url=LLM_URL, api_key="lm-studio")

        response = llm_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.question},
            ],
            temperature=request.temperature,
            max_tokens=1500,
        )

        answer = response.choices[0].message.content.strip()

    except Exception as e:
        logger.error(f"[Chat] LLM error: {e}")
        # Fallback: return context without LLM answer
        answer = (
            f"⚠️ Le LLM n'est pas accessible ({str(e)[:100]}). "
            f"Voici les {len(all_context)} extraits les plus pertinents trouvés dans le corpus :\n\n"
            + "\n\n---\n\n".join(
                f"📄 **{s['doc_title']}** (score: {s['score']:.2f})\n{s['text_preview']}..."
                for s in sources[:5]
            )
        )

    return ChatResponse(
        question=request.question,
        answer=answer,
        sources=sources,
        context_chunks=len(all_context),
        graph_enriched=request.use_graph,
    )


# ── Chunk Reader (proxy to Service A) ──

@router.get("/{project_id}/chunks/{chunk_id}")
async def get_chunk_content(
    project_id: str,
    chunk_id: str,
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific chunk's full content by chromadb_id. Proxy to Service A."""
    # Verify access
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Fetch from Service A
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(
                f"{STORAGE_URL}/storage/projects/{current_user.id}/{project_id}/chunks/{chunk_id}"
            )
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail="Chunk not found")
            resp.raise_for_status()
            chunk_data = resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Storage service error: {e}")

    # Enrich with PostgreSQL metadata
    chunk_result = await db.execute(
        select(Chunk).where(Chunk.chromadb_id == chunk_id)
    )
    chunk = chunk_result.scalar_one_or_none()

    doc_title = chunk_data.get("metadata", {}).get("title", "")
    doc_category = ""
    cluster_id = None
    relations = []

    if chunk:
        cluster_id = chunk.cluster_id
        from shared.models.orm import Document
        doc_result = await db.execute(
            select(Document).where(Document.id == chunk.document_id)
        )
        doc = doc_result.scalar_one_or_none()
        if doc:
            doc_title = doc.title or doc_title
            doc_category = doc.category or ""

        # Fetch relations
        rels_result = await db.execute(
            select(Relation).where(
                (Relation.chunk_a_id == chunk.id) | (Relation.chunk_b_id == chunk.id)
            ).limit(20)
        )
        for r in rels_result.scalars().all():
            connected_id = str(r.chunk_b_id) if str(r.chunk_a_id) == str(chunk.id) else str(r.chunk_a_id)
            relations.append({
                "type": r.type,
                "intensite": r.intensite,
                "confiance": r.confiance,
                "justification": r.justification,
                "connected_chunk_id": connected_id,
            })

    return {
        "chromadb_id": chunk_id,
        "text": chunk_data.get("document", chunk_data.get("text", "")),
        "metadata": chunk_data.get("metadata", {}),
        "doc_title": doc_title,
        "doc_category": doc_category,
        "cluster_id": cluster_id,
        "relations": relations,
    }


# ── Reformat chunk via LLM ──

class ReformatRequest(BaseModel):
    text: str
    doc_title: str = ""

@router.post("/{project_id}/reformat")
async def reformat_chunk(
    project_id: str,
    request: ReformatRequest,
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Use LLM to reformat a raw chunk text into clean, readable markdown."""
    # Verify access
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    prompt = f"""Tu es un assistant qui reformate des extraits de documents pédagogiques.

Reformate le texte brut suivant en Markdown clair et lisible :
- Ajoute des titres (##) et sous-titres (###) si pertinent
- Organise en paragraphes aérés
- Mets en **gras** les concepts importants
- Utilise des listes à puces quand c'est approprié
- Corrige les artefacts d'extraction PDF (mots coupés, espaces manquants)
- Conserve TOUT le contenu, ne résume pas
- Si c'est un tableau, reformate-le en tableau Markdown

Document : {request.doc_title}

TEXTE BRUT :
{request.text[:4000]}"""

    try:
        from openai import OpenAI
        llm_client = OpenAI(base_url=LLM_URL, api_key="lm-studio")

        response = llm_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": "Tu reformates des textes en Markdown propre et lisible. Tu ne résumes jamais, tu conserves tout le contenu."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=2000,
        )

        formatted = response.choices[0].message.content.strip()
        return {"formatted": formatted}

    except Exception as e:
        logger.error(f"[Reformat] LLM error: {e}")
        raise HTTPException(status_code=502, detail=f"LLM non disponible: {str(e)[:100]}")