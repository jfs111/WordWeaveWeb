# services/service_b/app/services/chunker.py
"""Text chunker with overlap — adapted from POC run_rncp_pipeline.py"""

from typing import List, Dict, Any
import logging

logger = logging.getLogger("service-b.chunker")


class TextChunker:
    """
    Splits text into word-based chunks with configurable overlap.
    Adapted from POC: RNCPPipeline.create_chunks()
    """

    def __init__(self, chunk_size: int = 1500, chunk_overlap: int = 200, min_chunk_words: int = 10):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_words = min_chunk_words

    def chunk(self, text: str, doc_id: str, metadata: Dict[str, Any] = {}) -> List[Dict]:
        """
        Split text into overlapping chunks.
        Returns list of chunk dicts with text, positions, context.
        """
        words = text.split()

        # If text is too short for even one chunk, return it as a single chunk
        if len(words) < self.chunk_size and len(words) >= self.min_chunk_words:
            chunk_id = f"{doc_id}_chunk_0"
            chunk_text = " ".join(words)
            return [{
                "chunk_id": chunk_id,
                "text": chunk_text,
                "char_start": 0,
                "char_end": len(chunk_text),
                "word_count": len(words),
                "position": 0,
                "context_before": "",
                "context_after": "",
                "doc_id": doc_id,
                "metadata": metadata,
            }]

        chunks = []
        step = self.chunk_size - self.chunk_overlap

        positions = list(range(0, len(words), step))

        for idx, start in enumerate(positions):
            chunk_words = words[start:start + self.chunk_size]

            if len(chunk_words) < self.min_chunk_words:
                continue

            chunk_text = " ".join(chunk_words)

            # Approximate char positions
            char_start = len(" ".join(words[:start])) + (1 if start > 0 else 0)
            char_end = char_start + len(chunk_text)

            # Context: last 75 words of previous chunk, first 75 of next
            context_before = ""
            if start > 0:
                ctx_words = words[max(0, start - 75):start]
                context_before = " ".join(ctx_words)

            context_after = ""
            next_start = start + self.chunk_size
            if next_start < len(words):
                ctx_words = words[next_start:next_start + 75]
                context_after = " ".join(ctx_words)

            chunk_id = f"{doc_id}_chunk_{len(chunks)}"

            chunks.append({
                "chunk_id": chunk_id,
                "text": chunk_text,
                "char_start": char_start,
                "char_end": char_end,
                "word_count": len(chunk_words),
                "position": idx,
                "context_before": context_before,
                "context_after": context_after,
                "doc_id": doc_id,
                "metadata": metadata,
            })

        logger.info(f"Chunked doc '{doc_id}': {len(words)} words → {len(chunks)} chunks")
        return chunks
