# tests/shared/test_auto_hop.py
"""Unit tests for Auto-Hop traversal logic.

The DB session is fully mocked — no real database is needed.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../"))

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import asdict

from shared.utils.auto_hop import (
    auto_hop_traversal,
    AutoHopResult,
    HopResult,
    DEFAULT_BUDGET,
    DEFAULT_MAX_HOPS,
    DEFAULT_MIN_SIMILARITY,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_relation(chunk_a_id: str, chunk_b_id: str, similarity: float,
                   rel_type: str = "COMPLEMENTAIRE", justification: str = "ok"):
    r = MagicMock()
    r.chunk_a_id = chunk_a_id
    r.chunk_b_id = chunk_b_id
    r.similarite_cosinus = similarity
    r.type = rel_type
    r.justification = justification
    return r


def _make_chunk(chunk_id: str, document_id: str = "doc-1",
                chromadb_id: str = "chroma-1", cluster_id: int = 0):
    c = MagicMock()
    c.id = chunk_id
    c.document_id = document_id
    c.chromadb_id = chromadb_id
    c.cluster_id = cluster_id
    return c


def _make_document(title: str = "My Doc"):
    d = MagicMock()
    d.title = title
    return d


def _build_db_mock(relations_per_chunk: dict, chunks: dict, documents: dict):
    """
    Build a mock AsyncSession whose execute() returns:
      - relations when queried for a chunk_id
      - chunk when queried by chunk id
      - document when queried
    """
    db = AsyncMock()

    async def fake_execute(query):
        # Inspect the query to decide what to return
        query_str = str(query)
        result = MagicMock()

        # Check if it's a Relation query (contains chunk id in WHERE clause)
        for chunk_id, rels in relations_per_chunk.items():
            if chunk_id in query_str:
                scalars_mock = MagicMock()
                scalars_mock.all.return_value = rels
                result.scalars.return_value = scalars_mock
                return result

        # Check if it's a Chunk query
        for chunk_id, chunk in chunks.items():
            if chunk_id in query_str:
                result.scalar_one_or_none.return_value = chunk
                return result

        # Fallback: document query
        for doc_id, doc in documents.items():
            if doc_id in query_str:
                result.scalar_one_or_none.return_value = doc
                return result

        # Default empty
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result.scalars.return_value = scalars_mock
        result.scalar_one_or_none.return_value = None
        return result

    db.execute = fake_execute
    return db


# ── We need a simpler mock approach for async tests ───────────────────────────

class MockExecuteResult:
    def __init__(self, scalars_list=None, scalar_one=None):
        self._scalars_list = scalars_list or []
        self._scalar_one = scalar_one

    def scalars(self):
        m = MagicMock()
        m.all.return_value = self._scalars_list
        return m

    def scalar_one_or_none(self):
        return self._scalar_one


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_relations_stops_immediately():
    """When there are no relations from the start chunk, traversal stops."""
    db = AsyncMock()
    db.execute.return_value = MockExecuteResult(scalars_list=[])

    result = await auto_hop_traversal(
        db=db,
        start_chunk_id="chunk-start",
        project_id="proj-1",
    )

    assert result.total_hops == 0
    assert result.neighbors == []
    assert result.stopped_reason == "no_neighbors"


@pytest.mark.asyncio
async def test_result_has_correct_start_chunk():
    db = AsyncMock()
    db.execute.return_value = MockExecuteResult(scalars_list=[])

    result = await auto_hop_traversal(db=db, start_chunk_id="chunk-42", project_id="proj-1")
    assert result.start_chunk_id == "chunk-42"


@pytest.mark.asyncio
async def test_default_budget_is_preserved():
    db = AsyncMock()
    db.execute.return_value = MockExecuteResult(scalars_list=[])

    result = await auto_hop_traversal(db=db, start_chunk_id="c1", project_id="proj-1")
    assert result.budget_initial == DEFAULT_BUDGET


@pytest.mark.asyncio
async def test_custom_budget_is_preserved():
    db = AsyncMock()
    db.execute.return_value = MockExecuteResult(scalars_list=[])

    result = await auto_hop_traversal(db=db, start_chunk_id="c1", project_id="proj-1", budget=2.0)
    assert result.budget_initial == 2.0


@pytest.mark.asyncio
async def test_max_hops_respected():
    """Ensure traversal never exceeds max_hops even with infinite budget."""
    call_count = 0

    async def execute_mock(query):
        nonlocal call_count
        call_count += 1
        # Always return one relation pointing to a new chunk
        # We cycle through chunk IDs based on call count
        # But since visited prevents revisiting, we need distinct IDs.
        # This simplified mock returns same neighbor each time — but visited prevents looping.
        rel = _make_relation("c0", f"c{call_count}", similarity=0.99)
        result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = [rel]
        result.scalars.return_value = scalars
        result.scalar_one_or_none.return_value = None
        return result

    db = AsyncMock()
    db.execute = execute_mock

    result = await auto_hop_traversal(
        db=db, start_chunk_id="c0", project_id="proj-1",
        max_hops=3, budget=100.0,
    )
    assert result.total_hops <= 3


@pytest.mark.asyncio
async def test_visited_chunks_not_revisited():
    """A chunk already visited must not appear twice in the result."""
    # Setup: chunk c1 → c2 → c1 (cycle) — c1 is already visited
    rel_c1_to_c2 = _make_relation("c1", "c2", similarity=0.9)
    rel_c2_to_c1 = _make_relation("c2", "c1", similarity=0.9)

    call_order = []

    async def execute_mock(query):
        query_str = str(query)
        result = MagicMock()
        # Relations query
        if "c2" in query_str and "chunk_a_id" in query_str or "chunk_b_id" in query_str:
            scalars = MagicMock()
            scalars.all.return_value = [rel_c2_to_c1]
            result.scalars.return_value = scalars
        else:
            scalars = MagicMock()
            scalars.all.return_value = [rel_c1_to_c2]
            result.scalars.return_value = scalars
        result.scalar_one_or_none.return_value = None
        return result

    db = AsyncMock()
    db.execute = execute_mock

    result = await auto_hop_traversal(
        db=db, start_chunk_id="c1", project_id="proj-1",
        max_hops=5, budget=10.0,
    )

    # Check no duplicate chunk IDs in result
    chunk_ids = [n.chunk_id for n in result.neighbors]
    assert len(chunk_ids) == len(set(chunk_ids))


@pytest.mark.asyncio
async def test_low_similarity_below_min_is_ignored():
    """Relations with similarity < min_similarity must not be traversed."""
    rel = _make_relation("c1", "c2", similarity=0.05)  # below default 0.1

    async def execute_mock(query):
        result = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = [rel]
        result.scalars.return_value = scalars
        result.scalar_one_or_none.return_value = None
        return result

    db = AsyncMock()
    db.execute = execute_mock

    result = await auto_hop_traversal(
        db=db, start_chunk_id="c1", project_id="proj-1",
        min_similarity=0.1,
    )
    assert result.total_hops == 0
    assert result.stopped_reason == "no_neighbors"


@pytest.mark.asyncio
async def test_budget_exhausted_stops_traversal():
    """When budget drops to 0, traversal must stop."""
    # similarity=0.5 → cost=0.5 → two hops would cost 1.0 (entire budget)
    rel = _make_relation("c1", "c2", similarity=0.5)

    call_num = [0]

    async def execute_mock(query):
        call_num[0] += 1
        result = MagicMock()
        scalars = MagicMock()
        # After first hop, offer c3 from c2 with cost > remaining budget
        rel2 = _make_relation("c2", "c3", similarity=0.1)  # cost=0.9
        scalars.all.return_value = [rel if call_num[0] == 1 else rel2]
        result.scalars.return_value = scalars
        result.scalar_one_or_none.return_value = None
        return result

    db = AsyncMock()
    db.execute = execute_mock

    result = await auto_hop_traversal(
        db=db, start_chunk_id="c1", project_id="proj-1",
        budget=0.5,  # Only enough for one hop of cost 0.5
    )
    assert result.budget_used <= 0.5


@pytest.mark.asyncio
async def test_hop_result_fields_are_populated():
    """Check that a HopResult has all expected fields non-None when chunk exists."""
    rel = _make_relation("c1", "c2", similarity=0.95, rel_type="PREREQUIS", justification="test")
    chunk = _make_chunk("c2", document_id="doc-99", chromadb_id="chroma-99", cluster_id=3)
    doc = _make_document("Mon Document")

    execute_calls = [0]

    async def execute_mock(query):
        execute_calls[0] += 1
        result = MagicMock()
        if execute_calls[0] == 1:
            # Relations for c1
            scalars = MagicMock()
            scalars.all.return_value = [rel]
            result.scalars.return_value = scalars
        elif execute_calls[0] == 2:
            # Relations for c2 (second hop — return nothing to stop)
            scalars = MagicMock()
            scalars.all.return_value = []
            result.scalars.return_value = scalars
        elif execute_calls[0] == 3:
            # Chunk query
            result.scalar_one_or_none.return_value = chunk
        elif execute_calls[0] == 4:
            # Document query
            result.scalar_one_or_none.return_value = doc
        else:
            scalars = MagicMock()
            scalars.all.return_value = []
            result.scalars.return_value = scalars
            result.scalar_one_or_none.return_value = None
        return result

    db = AsyncMock()
    db.execute = execute_mock

    result = await auto_hop_traversal(
        db=db, start_chunk_id="c1", project_id="proj-1",
        budget=10.0, max_hops=5,
    )

    assert result.total_hops >= 1
    hop = result.neighbors[0]
    assert hop.chunk_id == "c2"
    assert hop.hop == 1
    assert hop.relation_type == "PREREQUIS"
    assert hop.relation_similarity == pytest.approx(0.95)
    assert 0 < hop.budget_remaining <= 10.0


# ── AutoHopResult dataclass ───────────────────────────────────────────────────

class TestAutoHopResultDataclass:
    def test_default_neighbors_is_empty_list(self):
        r = AutoHopResult(start_chunk_id="c1")
        assert r.neighbors == []

    def test_total_hops_defaults_to_zero(self):
        r = AutoHopResult(start_chunk_id="c1")
        assert r.total_hops == 0

    def test_budget_used_defaults_to_zero(self):
        r = AutoHopResult(start_chunk_id="c1")
        assert r.budget_used == 0.0

    def test_stopped_reason_defaults_empty(self):
        r = AutoHopResult(start_chunk_id="c1")
        assert r.stopped_reason == ""

    def test_budget_initial_defaults_to_constant(self):
        r = AutoHopResult(start_chunk_id="c1")
        assert r.budget_initial == DEFAULT_BUDGET
