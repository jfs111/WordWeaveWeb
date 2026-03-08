# tests/service_b/test_chunker.py
"""Unit tests for TextChunker."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../"))

import pytest
from services.service_b.app.services.chunker import TextChunker


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def chunker():
    return TextChunker(chunk_size=10, chunk_overlap=2, min_chunk_words=3)


@pytest.fixture
def default_chunker():
    return TextChunker()


@pytest.fixture
def long_text():
    """50-word text that requires multiple chunks."""
    return " ".join([f"word{i}" for i in range(50)])


@pytest.fixture
def short_text():
    """5-word text (below chunk_size=10, above min=3)."""
    return "alpha beta gamma delta epsilon"


@pytest.fixture
def tiny_text():
    """2-word text (below min_chunk_words=3) → empty chunks."""
    return "only two"


# ── Construction ──────────────────────────────────────────────────────────────

class TestChunkerInit:
    def test_default_values(self):
        c = TextChunker()
        assert c.chunk_size == 1500
        assert c.chunk_overlap == 200
        assert c.min_chunk_words == 10

    def test_custom_values(self, chunker):
        assert chunker.chunk_size == 10
        assert chunker.chunk_overlap == 2
        assert chunker.min_chunk_words == 3


# ── Short text (single chunk) ─────────────────────────────────────────────────

class TestShortText:
    def test_returns_single_chunk(self, chunker, short_text):
        chunks = chunker.chunk(short_text, "doc1")
        assert len(chunks) == 1

    def test_chunk_id_format(self, chunker, short_text):
        chunks = chunker.chunk(short_text, "doc1")
        assert chunks[0]["chunk_id"] == "doc1_chunk_0"

    def test_chunk_text_matches_input(self, chunker, short_text):
        chunks = chunker.chunk(short_text, "doc1")
        assert chunks[0]["text"] == short_text.strip()

    def test_word_count_is_correct(self, chunker, short_text):
        chunks = chunker.chunk(short_text, "doc1")
        assert chunks[0]["word_count"] == len(short_text.split())

    def test_char_positions(self, chunker, short_text):
        chunks = chunker.chunk(short_text, "doc1")
        c = chunks[0]
        assert c["char_start"] == 0
        assert c["char_end"] == len(short_text)

    def test_context_empty_for_single_chunk(self, chunker, short_text):
        chunks = chunker.chunk(short_text, "doc1")
        assert chunks[0]["context_before"] == ""
        assert chunks[0]["context_after"] == ""

    def test_doc_id_preserved(self, chunker, short_text):
        chunks = chunker.chunk(short_text, "my-doc-42")
        assert chunks[0]["doc_id"] == "my-doc-42"

    def test_metadata_attached(self, chunker, short_text):
        meta = {"title": "Test Doc", "category": "RH"}
        chunks = chunker.chunk(short_text, "doc1", metadata=meta)
        assert chunks[0]["metadata"] == meta


# ── Text too small (below min_chunk_words) ────────────────────────────────────

class TestTinyText:
    def test_returns_empty_list(self, chunker, tiny_text):
        # 2 words < min_chunk_words=3 → no chunks
        chunks = chunker.chunk(tiny_text, "doc1")
        assert chunks == []

    def test_empty_string_returns_empty(self, chunker):
        chunks = chunker.chunk("", "doc1")
        assert chunks == []


# ── Long text (multiple chunks) ───────────────────────────────────────────────

class TestLongText:
    def test_produces_multiple_chunks(self, chunker, long_text):
        chunks = chunker.chunk(long_text, "doc1")
        assert len(chunks) > 1

    def test_chunk_ids_are_sequential(self, chunker, long_text):
        chunks = chunker.chunk(long_text, "doc1")
        for i, chunk in enumerate(chunks):
            assert chunk["chunk_id"] == f"doc1_chunk_{i}"

    def test_all_chunks_have_required_keys(self, chunker, long_text):
        required = {
            "chunk_id", "text", "char_start", "char_end",
            "word_count", "position", "context_before",
            "context_after", "doc_id", "metadata",
        }
        for chunk in chunker.chunk(long_text, "doc1"):
            assert required.issubset(set(chunk.keys()))

    def test_no_chunk_below_min_words(self, chunker, long_text):
        chunks = chunker.chunk(long_text, "doc1")
        for chunk in chunks:
            assert chunk["word_count"] >= chunker.min_chunk_words

    def test_overlap_creates_shared_words(self, chunker, long_text):
        """Adjacent chunks must share `chunk_overlap` words at boundaries."""
        chunks = chunker.chunk(long_text, "doc1")
        if len(chunks) < 2:
            pytest.skip("Not enough chunks to test overlap")
        words_0 = chunks[0]["text"].split()
        words_1 = chunks[1]["text"].split()
        # Last `overlap` words of chunk 0 should appear at start of chunk 1
        assert words_0[-chunker.chunk_overlap:] == words_1[:chunker.chunk_overlap]

    def test_context_before_non_empty_after_first(self, chunker, long_text):
        chunks = chunker.chunk(long_text, "doc1")
        if len(chunks) > 1:
            assert chunks[1]["context_before"] != ""

    def test_context_after_non_empty_before_last(self, chunker, long_text):
        chunks = chunker.chunk(long_text, "doc1")
        if len(chunks) > 1:
            assert chunks[0]["context_after"] != ""

    def test_char_end_greater_than_char_start(self, chunker, long_text):
        for chunk in chunker.chunk(long_text, "doc1"):
            assert chunk["char_end"] > chunk["char_start"]

    def test_default_metadata_is_empty_dict(self, chunker, long_text):
        chunks = chunker.chunk(long_text, "doc1")
        for chunk in chunks:
            assert isinstance(chunk["metadata"], dict)


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_text_exactly_chunk_size(self, chunker):
        text = " ".join([f"w{i}" for i in range(10)])  # exactly chunk_size=10
        chunks = chunker.chunk(text, "doc1")
        assert len(chunks) == 1

    def test_text_one_word_above_chunk_size(self, chunker):
        text = " ".join([f"w{i}" for i in range(11)])  # 11 words
        chunks = chunker.chunk(text, "doc1")
        assert len(chunks) >= 1

    def test_whitespace_only_text(self, chunker):
        chunks = chunker.chunk("   \n  \t  ", "doc1")
        assert chunks == []

    def test_doc_id_used_in_chunk_id(self, chunker, short_text):
        chunks = chunker.chunk(short_text, "special-doc-99")
        assert "special-doc-99" in chunks[0]["chunk_id"]

    def test_position_field_matches_index(self, chunker, long_text):
        chunks = chunker.chunk(long_text, "doc1")
        for i, chunk in enumerate(chunks):
            assert chunk["position"] == i

    def test_no_overlap_larger_than_chunk_size(self):
        """Known limitation: overlap >= chunk_size causes step=0 → ValueError.
        This documents a real edge case to guard in production code."""
        c = TextChunker(chunk_size=5, chunk_overlap=5, min_chunk_words=2)
        text = " ".join([f"w{i}" for i in range(20)])
        with pytest.raises(ValueError):
            c.chunk(text, "doc1")
