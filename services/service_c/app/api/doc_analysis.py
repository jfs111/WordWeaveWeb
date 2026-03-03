# services/service_c/app/api/doc_analysis.py
"""
Document Analysis Pipeline — Upload a PDF, analyze it against the existing corpus.
Pipeline: PDF → extract → chunk → embed → assign clusters → find links → LLM report
"""

import os
import uuid
import json
import io
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List, Optional
import httpx
import numpy as np
import logging
import PyPDF2

from shared.config.database import get_db, async_session
from shared.models.orm import Owner, Project, Document, Chunk, Relation, Job
from app.api.auth import get_current_user

router = APIRouter()
logger = logging.getLogger("service-c.doc-analysis")

STORAGE_URL = os.getenv("STORAGE_SERVICE_URL", "http://service-a:8000")
INTELLIGENCE_URL = os.getenv("INTELLIGENCE_SERVICE_URL", "http://service-b:8001")
LLM_URL = os.getenv("LLM_URL", "http://host.docker.internal:1234/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-oss-20b")


async def _update_job(db, job_id, status, progress, step=""):
    await db.execute(
        update(Job).where(Job.id == job_id).values(
            status=status, progress=progress, current_step=step,
        )
    )
    await db.commit()


@router.post("/{project_id}/analyze-document")
async def analyze_document(
    project_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted")

    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    content = await file.read()
    filename = file.filename

    job = Job(
        project_id=project_id, owner_id=current_user.id,
        type="document_analysis", status="running", progress=0,
        current_step="initialisation",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    async def _safe_run():
        try:
            logger.info(f"[DocAnalysis {job.id}] Task started!")
            print(f"[DocAnalysis {job.id}] Task started!", flush=True)
            await _run_analysis_pipeline(
                str(job.id), str(project_id), str(current_user.id),
                filename, content, project.chunking_size, project.chunking_overlap,
            )
        except Exception as e:
            logger.error(f"[DocAnalysis {job.id}] Task crashed: {e}", exc_info=True)
            print(f"[DocAnalysis {job.id}] Task crashed: {e}", flush=True)
            try:
                async with async_session() as db2:
                    await _update_job(db2, str(job.id), "failed", 0, str(e)[:200])
            except:
                pass

    asyncio.create_task(_safe_run())
    return {"job_id": str(job.id), "status": "running", "filename": filename}


@router.get("/{project_id}/analysis-report/{job_id}")
async def get_analysis_report(
    project_id: str, job_id: str,
    current_user: Owner = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Job).where(Job.id == job_id, Job.project_id == project_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed":
        return {"status": job.status, "progress": job.progress, "step": job.current_step}
    return {"status": "completed", "report": (job.output_data or {}).get("report", "Rapport non disponible")}


async def _run_analysis_pipeline(job_id, project_id, owner_id, filename, pdf_content, chunking_size, chunking_overlap):
    print(f"[DocAnalysis {job_id}] ===== PIPELINE STARTED for {filename} =====", flush=True)
    logger.info(f"[DocAnalysis {job_id}] ===== PIPELINE STARTED for {filename} =====")
    try:
        async with async_session() as db:
            try:
                # Step 1: Extract text
                await _update_job(db, job_id, "running", 5, "extraction_pdf")
                reader = PyPDF2.PdfReader(io.BytesIO(pdf_content))
                pages_text = [p.extract_text().strip() for p in reader.pages if p.extract_text()]
                full_text = "\n\n".join(pages_text)
                if len(full_text) < 50:
                    await _update_job(db, job_id, "failed", 0, "Texte trop court")
                    return
                logger.info(f"[DocAnalysis {job_id}] Extracted {len(full_text)} chars, {len(pages_text)} pages")

                # Step 2: Chunk
                await _update_job(db, job_id, "running", 10, "chunking")
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(f"{INTELLIGENCE_URL}/intelligence/chunk",
                        json={"text": full_text, "doc_id": f"analysis_{job_id}", "chunk_size": chunking_size, "chunk_overlap": chunking_overlap})
                    resp.raise_for_status()
                new_chunks = resp.json()
                if not new_chunks:
                    await _update_job(db, job_id, "failed", 0, "Aucun chunk")
                    return
                chunk_texts = [c["text"] for c in new_chunks]
                logger.info(f"[DocAnalysis {job_id}] {len(new_chunks)} chunks")

                # Step 3: Embed
                await _update_job(db, job_id, "running", 20, "embeddings")
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(f"{INTELLIGENCE_URL}/intelligence/embed", json={"texts": chunk_texts})
                    resp.raise_for_status()
                new_embeddings = resp.json()["embeddings"]
                logger.info(f"[DocAnalysis {job_id}] {len(new_embeddings)} embeddings")

                # Step 4: Cluster assignment
                await _update_job(db, job_id, "running", 30, "assignation_clusters")
                async with httpx.AsyncClient(timeout=120) as client:
                    resp = await client.get(f"{STORAGE_URL}/storage/projects/{owner_id}/{project_id}/embeddings")
                    resp.raise_for_status()
                existing_data = resp.json()
                existing_embeddings = np.array(existing_data["embeddings"])
                existing_ids = existing_data["chunk_ids"]

                chunks_result = await db.execute(
                    select(Chunk).where(Chunk.project_id == project_id, Chunk.cluster_id.isnot(None)))
                chromadb_to_cluster = {c.chromadb_id: c.cluster_id for c in chunks_result.scalars().all()}

                cluster_emb_map = {}
                for i, cid in enumerate(existing_ids):
                    cl = chromadb_to_cluster.get(cid)
                    if cl is not None and i < len(existing_embeddings):
                        cluster_emb_map.setdefault(cl, []).append(existing_embeddings[i])
                cluster_centers = {cid: np.mean(embs, axis=0) for cid, embs in cluster_emb_map.items()}

                chunk_assignments = []
                for i, emb in enumerate(new_embeddings):
                    emb_arr = np.array(emb)
                    best_c, best_d = 0, float("inf")
                    for cid, center in cluster_centers.items():
                        d = np.linalg.norm(emb_arr - center)
                        if d < best_d:
                            best_d, best_c = d, cid
                    chunk_assignments.append({"chunk_index": i, "text": chunk_texts[i], "cluster_id": best_c, "distance": float(best_d)})
                logger.info(f"[DocAnalysis {job_id}] Clusters assigned")

                # Step 5: Semantic search
                await _update_job(db, job_id, "running", 40, "recherche_liens")
                all_links = []
                for idx, ca in enumerate(chunk_assignments):
                    pct = 40 + int((idx / len(chunk_assignments)) * 30)
                    await _update_job(db, job_id, "running", pct, f"recherche_liens ({idx+1}/{len(chunk_assignments)})")
                    async with httpx.AsyncClient(timeout=30) as client:
                        resp = await client.post(
                            f"{STORAGE_URL}/storage/projects/{owner_id}/{project_id}/search",
                            json={"owner_id": owner_id, "project_id": project_id, "query_embedding": new_embeddings[idx], "n_results": 5})
                        if resp.status_code != 200:
                            continue
                        search_results = resp.json()

                    matches = []
                    for sr in search_results:
                        if sr.get("score", 0) < 0.05:
                            continue
                        cdb_id = sr["chunk_id"]
                        doc_title = sr.get("metadata", {}).get("title", "")
                        cr = await db.execute(select(Chunk).where(Chunk.chromadb_id == cdb_id))
                        db_chunk = cr.scalar_one_or_none()
                        if db_chunk:
                            dr = await db.execute(select(Document).where(Document.id == db_chunk.document_id))
                            doc = dr.scalar_one_or_none()
                            if doc:
                                doc_title = doc.title or doc_title
                        matches.append({"chromadb_id": cdb_id, "text_preview": sr.get("text", "")[:300],
                                        "score": sr.get("score", 0), "doc_title": doc_title,
                                        "cluster_id": chromadb_to_cluster.get(cdb_id)})
                    all_links.append({"chunk_index": idx, "chunk_text_preview": ca["text"][:200],
                                      "assigned_cluster": ca["cluster_id"], "matches": matches})
                logger.info(f"[DocAnalysis {job_id}] Links found for {len(all_links)} chunks")

                # Step 6: LLM analysis
                await _update_job(db, job_id, "running", 70, "analyse_llm")
                llm_analyses = []
                count = 0
                max_a = 15
                for lk in all_links:
                    if count >= max_a:
                        break
                    for match in [m for m in lk["matches"] if m["score"] > 0.07][:2]:
                        if count >= max_a:
                            break
                        await _update_job(db, job_id, "running", 70 + int((count / max_a) * 20), f"analyse_llm ({count+1}/{max_a})")
                        prompt = f"""Analyse la relation entre ces deux extraits de documents pédagogiques.

EXTRAIT A (nouveau document "{filename}"):
{lk['chunk_text_preview']}

EXTRAIT B (document existant "{match['doc_title']}"):
{match['text_preview']}

Réponds en JSON avec:
- "type": PREREQUIS, COMPLEMENTAIRE, SIMILAIRE, METHODOLOGIQUE, APPLICATION, SUITE_LOGIQUE ou TRANSVERSAL
- "intensite": FAIBLE, MOYENNE ou FORTE
- "justification": une phrase en français
"""
                        try:
                            from openai import OpenAI
                            llm = OpenAI(base_url=LLM_URL, api_key="lm-studio")
                            r = llm.chat.completions.create(model=LLM_MODEL, messages=[
                                {"role": "system", "content": "Réponds UNIQUEMENT en JSON valide."},
                                {"role": "user", "content": prompt}], temperature=0.2, max_tokens=300)
                            txt = r.choices[0].message.content.strip().replace("```json", "").replace("```", "").strip()
                            a = json.loads(txt)
                            llm_analyses.append({"chunk_index": lk["chunk_index"], "chunk_preview": lk["chunk_text_preview"][:150],
                                "match_doc": match["doc_title"], "match_preview": match["text_preview"][:150],
                                "score": match["score"], "type": a.get("type", "COMPLEMENTAIRE"),
                                "intensite": a.get("intensite", "MOYENNE"), "justification": a.get("justification", "")})
                            count += 1
                        except Exception as e:
                            logger.warning(f"[DocAnalysis {job_id}] LLM error: {e}")
                            count += 1
                logger.info(f"[DocAnalysis {job_id}] {len(llm_analyses)} relations analyzed")

                # Step 7: Report
                await _update_job(db, job_id, "running", 92, "generation_rapport")
                report = _generate_report(filename, len(pages_text), len(new_chunks), chunk_assignments, all_links, llm_analyses, cluster_centers)
                await db.execute(update(Job).where(Job.id == job_id).values(output_data={"report": report}))
                await _update_job(db, job_id, "completed", 100, "terminé")
                logger.info(f"[DocAnalysis {job_id}] ===== COMPLETED ({len(report)} chars) =====")

            except Exception as e:
                logger.error(f"[DocAnalysis {job_id}] Pipeline error: {e}", exc_info=True)
                try:
                    await _update_job(db, job_id, "failed", 0, str(e)[:500])
                except Exception:
                    pass
    except Exception as e:
        logger.error(f"[DocAnalysis {job_id}] Fatal error: {e}", exc_info=True)


def _generate_report(filename, n_pages, n_chunks, chunk_assignments, all_links, llm_analyses, cluster_centers):
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    cluster_counts = {}
    for ca in chunk_assignments:
        cid = ca["cluster_id"]
        cluster_counts[cid] = cluster_counts.get(cid, 0) + 1
    type_counts = {}
    for a in llm_analyses:
        type_counts[a.get("type", "AUTRE")] = type_counts.get(a.get("type", "AUTRE"), 0) + 1

    lines = [
        f"# 📊 Rapport d'analyse : {filename}",
        f"*Généré le {now}*\n", "---\n",
        "## 📋 Résumé", "| Métrique | Valeur |", "|----------|--------|",
        f"| Pages | {n_pages} |", f"| Chunks générés | {n_chunks} |",
        f"| Clusters identifiés | {len(cluster_counts)} |",
        f"| Relations analysées (LLM) | {len(llm_analyses)} |", "",
        "## 🎯 Distribution par cluster\n", "| Cluster | Chunks | % |", "|---------|--------|---|",
    ]
    for cid in sorted(cluster_counts.keys()):
        cnt = cluster_counts[cid]
        lines.append(f"| Cluster {cid} | {cnt} | {round(cnt/n_chunks*100,1)}% |")

    lines += ["", "## 🔗 Relations détectées\n"]
    if not llm_analyses:
        lines.append("*Aucune relation significative détectée.*\n")
    else:
        lines += ["### Répartition par type\n", "| Type | Nombre |", "|------|--------|"]
        for t in sorted(type_counts.keys()):
            lines.append(f"| {t} | {type_counts[t]} |")
        lines += ["", "### Détail des relations\n"]
        for i, a in enumerate(llm_analyses, 1):
            lines += [
                f"#### Relation {i} — {a['type']} ({a['intensite']})",
                f"**Nouveau document** (chunk {a['chunk_index']+1}) :",
                f"> {a['chunk_preview']}...\n",
                f"**Document existant** : *{a['match_doc']}*",
                f"> {a['match_preview']}...\n",
                f"**Justification** : {a['justification']}",
                f"- Score de similarité : {a['score']*100:.0f}%", "",
            ]

    lines.append("## 💡 Synthèse\n")
    if llm_analyses:
        mc = sorted(cluster_counts.keys(), key=lambda c: cluster_counts[c], reverse=True)[:3]
        mt = sorted(type_counts.keys(), key=lambda t: type_counts[t], reverse=True)[:3]
        rd = list(set(a["match_doc"] for a in llm_analyses if a["match_doc"]))[:5]
        lines.append(f"Le document **{filename}** a été découpé en **{n_chunks} chunks** répartis sur **{len(cluster_counts)} clusters**. Clusters principaux : {', '.join(f'Cluster {c}' for c in mc)}.\n")
        lines.append(f"L'analyse LLM a identifié **{len(llm_analyses)} relations**, principalement : {', '.join(mt)}.\n")
        lines += ["### Documents de référence liés\n"] + [f"- 📄 {d}" for d in rd]
    else:
        lines.append("Aucune relation significative détectée.")
    lines.append("\n---\n*Rapport généré par Graph-RAG Analysis Pipeline*")
    return "\n".join(lines)
