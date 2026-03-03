# services/service_c/app/api/documents.py
"""Documents API — Upload PDFs, trigger processing pipeline, list documents"""

import os
import uuid
import shutil
import asyncio
from pathlib import Path
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List, Optional
import httpx
import logging

from shared.config.database import get_db
from shared.models.orm import Owner, Project, Document, Chunk, Job
from app.api.auth import get_current_user

router = APIRouter()
logger = logging.getLogger("service-c.documents")

STORAGE_URL = os.getenv("STORAGE_SERVICE_URL", "http://service-a:8000")
INTELLIGENCE_URL = os.getenv("INTELLIGENCE_SERVICE_URL", "http://service-b:8001")
DOCUMENT_STORAGE = Path("/app/documents")

# Lock to serialize ChromaDB ingests (prevents race conditions on batch upload)
_ingest_lock = asyncio.Lock()


# ── Upload ──

@router.post("/{project_id}/documents/upload")
async def upload_document(
    project_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    category: str = Form(default=""),
    title: str = Form(default=""),
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a PDF document and trigger processing pipeline"""

    # 1. Verify project access
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 2. Check file type
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    # 3. Check quota
    if project.total_documents >= project.max_documents:
        raise HTTPException(status_code=403, detail=f"Document limit reached ({project.max_documents})")

    # 4. Save file to disk
    doc_dir = DOCUMENT_STORAGE / str(current_user.id) / str(project_id)
    doc_dir.mkdir(parents=True, exist_ok=True)

    file_id = str(uuid.uuid4())
    file_ext = Path(file.filename).suffix
    stored_name = f"{file_id}{file_ext}"
    file_path = doc_dir / stored_name

    file_size = 0
    with open(file_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):  # 1MB chunks
            f.write(chunk)
            file_size += len(chunk)

    file_size_mb = round(file_size / (1024 * 1024), 2)

    # 5. Check storage quota
    if project.total_storage_mb + file_size_mb > project.max_storage_mb:
        file_path.unlink()  # Delete the file
        raise HTTPException(status_code=403, detail="Storage quota exceeded")

    # 6. Create document record
    doc_title = title or Path(file.filename).stem.replace("_", " ").replace("-", " ")

    document = Document(
        project_id=project.id,
        filename=file.filename,
        title=doc_title,
        category=category or None,
        file_path=str(file_path),
        file_size_mb=file_size_mb,
        status="uploaded",
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    # 7. Create job
    job = Job(
        project_id=project.id,
        owner_id=current_user.id,
        type="ingest",
        status="pending",
        input_data={"document_id": str(document.id), "filename": file.filename},
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # 8. Launch pipeline in background
    background_tasks.add_task(
        run_ingest_pipeline,
        str(document.id),
        str(project.id),
        str(current_user.id),
        str(job.id),
        str(file_path),
        project.chunking_size,
        project.chunking_overlap,
    )

    return {
        "document_id": str(document.id),
        "job_id": str(job.id),
        "filename": file.filename,
        "file_size_mb": file_size_mb,
        "status": "processing",
        "message": "Pipeline started: extract → chunk → embed → cluster → ingest",
    }


# ── List Documents ──

@router.get("/{project_id}/documents")
async def list_documents(
    project_id: str,
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all documents in a project"""
    # Verify access
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    result = await db.execute(
        select(Document)
        .where(Document.project_id == project_id)
        .order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()

    return [
        {
            "id": str(d.id),
            "filename": d.filename,
            "title": d.title,
            "category": d.category,
            "file_size_mb": d.file_size_mb,
            "pages": d.pages,
            "status": d.status,
            "total_chunks": d.total_chunks,
            "total_relations": d.total_relations,
            "error_message": d.error_message,
            "created_at": d.created_at.isoformat(),
            "processed_at": d.processed_at.isoformat() if d.processed_at else None,
        }
        for d in docs
    ]


# ── Job Status ──

@router.get("/{project_id}/jobs")
async def list_jobs(
    project_id: str,
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List recent jobs for a project"""
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")

    result = await db.execute(
        select(Job)
        .where(Job.project_id == project_id)
        .order_by(Job.created_at.desc())
        .limit(20)
    )
    jobs = result.scalars().all()

    return [
        {
            "id": str(j.id),
            "type": j.type,
            "status": j.status,
            "progress": j.progress,
            "current_step": j.current_step,
            "error_message": j.error_message,
            "created_at": j.created_at.isoformat(),
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
        }
        for j in jobs
    ]


# ═══════════════════════════════════════════
# BACKGROUND PIPELINE
# ═══════════════════════════════════════════

async def run_ingest_pipeline(
    document_id: str,
    project_id: str,
    owner_id: str,
    job_id: str,
    file_path: str,
    chunk_size: int,
    chunk_overlap: int,
):
    """
    Full ingestion pipeline (runs in background):
    1. Extract text from PDF
    2. Chunk text (Service B)
    3. Generate embeddings (Service B)
    4. Ingest into ChromaDB (Service A)
    5. Update PostgreSQL stats
    """
    from shared.config.database import async_session

    async with async_session() as db:
        try:
            # Update job status
            await _update_job(db, job_id, "running", 0, "extracting_pdf")
            await _update_document(db, document_id, status="processing")

            # ── STEP 1: Extract PDF text ──
            logger.info(f"[Pipeline {job_id}] Step 1: Extracting PDF...")
            text, pages = _extract_pdf_text(file_path)

            if not text or len(text) < 50:
                raise ValueError("Could not extract text from PDF (empty or too short)")

            await db.execute(
                update(Document).where(Document.id == document_id).values(pages=pages)
            )
            await db.commit()
            await _update_job(db, job_id, "running", 15, "chunking")

            # ── STEP 2: Chunk text via Service B ──
            logger.info(f"[Pipeline {job_id}] Step 2: Chunking ({len(text)} chars)...")
            async with httpx.AsyncClient(timeout=120) as client:
                chunk_resp = await client.post(
                    f"{INTELLIGENCE_URL}/intelligence/chunk",
                    json={
                        "text": text,
                        "doc_id": document_id,
                        "chunk_size": chunk_size,
                        "chunk_overlap": chunk_overlap,
                        "metadata": {"project_id": project_id, "owner_id": owner_id},
                    }
                )
                chunk_resp.raise_for_status()
                chunks = chunk_resp.json()

            logger.info(f"[Pipeline {job_id}] Got {len(chunks)} chunks")
            await _update_job(db, job_id, "running", 35, "embedding")

            # ── STEP 3: Embed via Service B ──
            logger.info(f"[Pipeline {job_id}] Step 3: Generating embeddings...")
            chunk_texts = [c["text"] for c in chunks]

            async with httpx.AsyncClient(timeout=300) as client:
                embed_resp = await client.post(
                    f"{INTELLIGENCE_URL}/intelligence/embed",
                    json={"texts": chunk_texts}
                )
                embed_resp.raise_for_status()
                embed_data = embed_resp.json()
                embeddings = embed_data["embeddings"]

            logger.info(f"[Pipeline {job_id}] Got {len(embeddings)} embeddings (dim={embed_data['dimension']})")
            await _update_job(db, job_id, "running", 60, "ingesting_chromadb")

            # ── STEP 4: Ingest into ChromaDB via Service A (serialized to prevent race conditions) ──
            logger.info(f"[Pipeline {job_id}] Step 4: Waiting for ingest lock...")
            async with _ingest_lock:
                logger.info(f"[Pipeline {job_id}] Step 4: Ingesting into ChromaDB...")

                # Build chunk payloads
                ingest_chunks = []
                for i, chunk in enumerate(chunks):
                    ingest_chunks.append({
                        "chunk_id": chunk["chunk_id"],
                        "text": chunk["text"],
                        "embedding": embeddings[i],
                        "metadata": {
                            "doc_id": document_id,
                            "project_id": project_id,
                            "owner_id": owner_id,
                            "title": chunk.get("metadata", {}).get("title", ""),
                            "category": chunk.get("metadata", {}).get("category", ""),
                            "position": chunk["position"],
                            "word_count": chunk["word_count"],
                            "char_start": chunk["char_start"],
                            "char_end": chunk["char_end"],
                        }
                    })

                async with httpx.AsyncClient(timeout=120) as client:
                    ingest_resp = await client.post(
                        f"{STORAGE_URL}/storage/projects/{owner_id}/{project_id}/ingest",
                        json={
                            "owner_id": owner_id,
                            "project_id": project_id,
                            "chunks": ingest_chunks,
                        }
                    )
                    ingest_resp.raise_for_status()

            logger.info(f"[Pipeline {job_id}] ChromaDB ingest done")
            await _update_job(db, job_id, "running", 85, "updating_metadata")

            # ── STEP 5: Save chunks in PostgreSQL + update stats ──
            logger.info(f"[Pipeline {job_id}] Step 5: Updating PostgreSQL...")

            for i, chunk in enumerate(chunks):
                chunk_record = Chunk(
                    document_id=document_id,
                    project_id=project_id,
                    chunk_index=chunk["position"],
                    chromadb_id=chunk["chunk_id"],
                    text_preview=chunk["text"][:500],
                    word_count=chunk["word_count"],
                    char_start=chunk["char_start"],
                    char_end=chunk["char_end"],
                )
                db.add(chunk_record)

            # Update document
            await db.execute(
                update(Document).where(Document.id == document_id).values(
                    status="processed",
                    total_chunks=len(chunks),
                    processed_at=datetime.now(timezone.utc),
                )
            )

            # Update project stats
            await db.execute(
                update(Project).where(Project.id == project_id).values(
                    total_documents=Project.total_documents + 1,
                    total_chunks=Project.total_chunks + len(chunks),
                    total_storage_mb=Project.total_storage_mb + float(
                        (await db.execute(
                            select(Document.file_size_mb).where(Document.id == document_id)
                        )).scalar() or 0
                    ),
                )
            )

            await db.commit()

            # ── DONE ──
            await _update_job(db, job_id, "completed", 100, "done")
            logger.info(f"[Pipeline {job_id}] ✅ Pipeline completed: {len(chunks)} chunks ingested")

        except Exception as e:
            logger.error(f"[Pipeline {job_id}] ❌ Error: {e}")
            await _update_document(db, document_id, status="error", error=str(e))
            await _update_job(db, job_id, "failed", None, "error", error=str(e))


# ── Helpers ──

def _extract_pdf_text(file_path: str) -> tuple:
    """Extract text from PDF using PyPDF2"""
    import PyPDF2

    text = ""
    pages = 0
    try:
        with open(file_path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            pages = len(reader.pages)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        logger.error(f"PDF extraction error: {e}")

    # Clean
    import re
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    text = text.replace('\x00', '')

    return text.strip(), pages


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


async def _update_document(db, document_id, status=None, error=None):
    values = {}
    if status:
        values["status"] = status
    if error:
        values["error_message"] = error
    if values:
        await db.execute(update(Document).where(Document.id == document_id).values(**values))
        await db.commit()