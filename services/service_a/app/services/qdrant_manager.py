# services/service_a/app/services/qdrant_manager.py
"""Qdrant Manager — tenant-isolated collections"""

import os
import uuid
import hashlib
from typing import List, Dict, Any, Optional
import logging
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, Distance, PointStruct,
    Filter, FieldCondition, MatchValue,
)

logger = logging.getLogger("service-a.qdrant")

QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))


def _str_to_uuid(s: str) -> str:
    """Convert any string to a deterministic UUID (for Qdrant point IDs)"""
    return str(uuid.UUID(hashlib.md5(s.encode()).hexdigest()))

logger = logging.getLogger("service-a.qdrant")

QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))


class QdrantManager:
    """
    Manages Qdrant collections with tenant isolation per owner/project.
    Each project gets its own Qdrant collection: proj_{project_id}
    """

    def __init__(self):
        self._client = None

    @property
    def client(self) -> QdrantClient:
        if self._client is None:
            self._client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=60)
        return self._client

    def _collection_name(self, owner_id: str, project_id: str) -> str:
        return f"proj_{project_id}"

    def _ensure_collection(self, owner_id: str, project_id: str) -> str:
        name = self._collection_name(owner_id, project_id)
        collections = [c.name for c in self.client.get_collections().collections]
        if name not in collections:
            self.client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIM,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(f"Created collection: {name}")
        return name

    # ── INGEST ──

    def ingest_batch(self, owner_id: str, project_id: str, chunks: list) -> Dict:
        """Ingest a batch of chunks into project collection"""
        name = self._ensure_collection(owner_id, project_id)

        points = []
        for chunk in chunks:
            # Build payload (metadata + text + original chunk_id)
            payload = {"text": chunk.text, "chunk_id": chunk.chunk_id}
            for k, v in chunk.metadata.items():
                if isinstance(v, (str, int, float, bool)):
                    payload[k] = v
                else:
                    payload[k] = str(v)
            payload["owner_id"] = owner_id
            payload["project_id"] = project_id

            points.append(PointStruct(
                id=_str_to_uuid(chunk.chunk_id),
                vector=chunk.embedding,
                payload=payload,
            ))

        # Batch upsert (Qdrant handles large batches natively)
        batch_size = 100
        for i in range(0, len(points), batch_size):
            self.client.upsert(
                collection_name=name,
                points=points[i:i + batch_size],
                wait=True,
            )

        logger.info(f"Ingested {len(points)} chunks → {name}")
        return {"count": len(points), "collection": name}

    # ── SEARCH ──

    def search(
        self,
        owner_id: str,
        project_id: str,
        query_embedding: List[float],
        n_results: int = 10,
        where_filter: Optional[Dict] = None
    ) -> List[Dict]:
        """Semantic search in project collection"""
        name = self._ensure_collection(owner_id, project_id)

        # Build Qdrant filter from where_filter
        query_filter = None
        if where_filter:
            conditions = []
            for k, v in where_filter.items():
                conditions.append(FieldCondition(key=k, match=MatchValue(value=v)))
            if conditions:
                query_filter = Filter(must=conditions)

        results = self.client.search(
            collection_name=name,
            query_vector=query_embedding,
            limit=n_results,
            query_filter=query_filter,
            with_payload=True,
            with_vectors=False,
        )

        output = []
        for hit in results:
            payload = hit.payload or {}
            text = payload.pop("text", "")
            chunk_id = payload.pop("chunk_id", str(hit.id))
            # Cosine distance: score is similarity (0-1), distance = 1 - score
            score = hit.score  # Qdrant cosine returns similarity directly
            distance = 1.0 - score
            output.append({
                "chunk_id": chunk_id,
                "text": text,
                "metadata": payload,
                "distance": distance,
                "score": score,
            })

        return output

    # ── GET / LIST ──

    def get_chunk(self, owner_id: str, project_id: str, chunk_id: str) -> Optional[Dict]:
        """Get a single chunk by ID"""
        name = self._ensure_collection(owner_id, project_id)
        try:
            points = self.client.retrieve(
                collection_name=name,
                ids=[_str_to_uuid(chunk_id)],
                with_payload=True,
                with_vectors=True,
            )
            if points:
                p = points[0]
                payload = p.payload or {}
                text = payload.pop("text", "")
                original_id = payload.pop("chunk_id", chunk_id)
                return {
                    "chunk_id": original_id,
                    "text": text,
                    "metadata": payload,
                    "embedding": p.vector if p.vector else [],
                }
        except Exception as e:
            logger.error(f"Get chunk error: {e}")
        return None

    def list_chunks(
        self,
        owner_id: str,
        project_id: str,
        offset: int = 0,
        limit: int = 50,
        cluster_id: Optional[int] = None
    ) -> Dict:
        """List chunks with pagination"""
        name = self._ensure_collection(owner_id, project_id)

        query_filter = None
        if cluster_id is not None:
            query_filter = Filter(must=[
                FieldCondition(key="cluster_id", match=MatchValue(value=cluster_id))
            ])

        # Use scroll for pagination
        results, _next = self.client.scroll(
            collection_name=name,
            limit=limit,
            offset=offset,
            scroll_filter=query_filter,
            with_payload=True,
            with_vectors=False,
        )

        total = self.client.count(collection_name=name).count

        chunks = []
        for p in results:
            payload = p.payload or {}
            text = payload.pop("text", "")
            chunk_id = payload.pop("chunk_id", str(p.id))
            chunks.append({
                "chunk_id": chunk_id,
                "text": text,
                "metadata": payload,
            })

        return {
            "chunks": chunks,
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    # ── BULK EMBEDDINGS ──

    def get_all_embeddings(self, owner_id: str, project_id: str) -> Dict:
        """Get ALL embeddings for a project (for clustering). Uses scroll pagination."""
        name = self._ensure_collection(owner_id, project_id)

        total = self.client.count(collection_name=name).count
        print(f"[Qdrant] Collection {name}: {total} items", flush=True)

        if total == 0:
            return {"chunk_ids": [], "embeddings": [], "metadatas": [], "documents": [], "total": 0}

        all_ids = []
        all_embeddings = []
        all_metadatas = []
        all_documents = []

        # Scroll through ALL points with vectors
        offset = None
        batch_num = 0
        while True:
            results, next_offset = self.client.scroll(
                collection_name=name,
                limit=100,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )

            if not results:
                break

            batch_num += 1
            for p in results:
                payload = p.payload or {}
                text = payload.pop("text", "")
                chunk_id = payload.pop("chunk_id", str(p.id))

                all_ids.append(chunk_id)
                all_embeddings.append(p.vector if isinstance(p.vector, list) else list(p.vector))
                all_metadatas.append(payload)
                all_documents.append(text)

            print(f"[Qdrant] Batch {batch_num}: {len(results)} points", flush=True)

            if next_offset is None:
                break
            offset = next_offset

        print(f"[Qdrant] Returning {len(all_ids)} ids, {len(all_embeddings)} embeddings", flush=True)
        return {
            "chunk_ids": all_ids,
            "embeddings": all_embeddings,
            "metadatas": all_metadatas,
            "documents": all_documents,
            "total": len(all_ids),
        }

    # ── UPDATE METADATA ──

    def update_cluster_metadata(self, owner_id: str, project_id: str, updates: List[Dict]) -> int:
        """Update cluster_id in payload for chunks"""
        name = self._ensure_collection(owner_id, project_id)
        updated = 0

        for u in updates:
            try:
                self.client.set_payload(
                    collection_name=name,
                    payload={"cluster_id": u["cluster_id"]},
                    points=[_str_to_uuid(u["chunk_id"])],
                )
                updated += 1
            except Exception as e:
                logger.warning(f"Update cluster_id for {u['chunk_id']}: {e}")

        logger.info(f"Updated cluster_id for {updated} chunks in {name}")
        return updated

    # ── STATS ──

    def get_stats(self, owner_id: str, project_id: str) -> Dict:
        """Get collection stats"""
        name = self._ensure_collection(owner_id, project_id)
        count = self.client.count(collection_name=name).count
        return {
            "total_chunks": count,
            "collection_name": name,
        }

    # ── DELETE ──

    def delete_collection(self, owner_id: str, project_id: str):
        """Delete entire project collection"""
        name = self._collection_name(owner_id, project_id)
        try:
            self.client.delete_collection(collection_name=name)
            logger.info(f"Deleted collection {name}")
        except Exception:
            pass