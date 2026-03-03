# services/service_b/app/services/embedder.py
"""Embedding service — SentenceTransformers (from POC)"""

import os
import numpy as np
from typing import List
import logging

logger = logging.getLogger("service-b.embedder")

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")

# Lazy-loaded model singleton
_model = None


def _get_model():
    global _model
    if _model is None:
        logger.info(f"Loading embedding model: {MODEL_NAME}...")
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(MODEL_NAME)
        logger.info(f"Model loaded. Dimension: {_model.get_sentence_embedding_dimension()}")
    return _model


class EmbeddingService:
    """
    Generate embeddings using SentenceTransformers.
    Adapted from POC: RNCPPipeline.generate_embeddings()
    """

    def __init__(self):
        self.model_name = MODEL_NAME

    def embed(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """Generate embeddings for a list of texts"""
        model = _get_model()

        embeddings = model.encode(
            texts,
            show_progress_bar=False,
            batch_size=batch_size,
            convert_to_numpy=True,
        )

        logger.info(f"Embedded {len(texts)} texts → shape {embeddings.shape}")
        return embeddings.tolist()

    def embed_single(self, text: str) -> List[float]:
        """Embed a single text (for queries)"""
        result = self.embed([text])
        return result[0]

    @property
    def dimension(self) -> int:
        model = _get_model()
        return model.get_sentence_embedding_dimension()
