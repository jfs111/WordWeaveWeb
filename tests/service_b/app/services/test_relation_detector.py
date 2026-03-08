# tests/service_b/test_relation_detector.py
"""Unit tests for RelationDetector — LLM calls are mocked."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../"))

import pytest
import numpy as np
from unittest.mock import MagicMock, patch

from services.service_b.app.services.relation_detector import RelationDetector


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def detector():
    return RelationDetector(similarity_threshold=0.5, max_pairs_per_cluster=100)


def _make_embeddings(n: int, dim: int = 8, seed: int = 0):
    """Create unit-normalised embeddings so cosine similarity is meaningful."""
    rng = np.random.default_rng(seed)
    raw = rng.random((n, dim))
    norms = np.linalg.norm(raw, axis=1, keepdims=True)
    return (raw / norms).tolist()


def _mock_llm_response(payload: dict):
    """Build an OpenAI-style mock completion response."""
    import json
    msg = MagicMock()
    msg.content = json.dumps(payload)
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    return response


# ── Stats ─────────────────────────────────────────────────────────────────────

class TestStats:
    def test_initial_stats_all_zero(self, detector):
        s = detector.get_stats()
        assert all(v == 0 for v in s.values())

    def test_reset_stats_clears_values(self, detector):
        detector.stats["llm_calls"] = 5
        detector.reset_stats()
        assert detector.get_stats()["llm_calls"] == 0

    def test_stats_keys_present(self, detector):
        expected = {
            "total_pairs_analyzed", "total_relations_found",
            "llm_calls", "filtered_by_cosine", "errors"
        }
        assert expected.issubset(set(detector.get_stats().keys()))


# ── detect_relations_for_cluster: degenerate cases ───────────────────────────

class TestClusterDegenerate:
    def test_single_chunk_returns_empty(self, detector):
        emb = _make_embeddings(1)
        result = detector.detect_relations_for_cluster(0, ["c1"], ["text"], emb, [{}])
        assert result == []

    def test_zero_chunks_returns_empty(self, detector):
        result = detector.detect_relations_for_cluster(0, [], [], [], [])
        assert result == []


# ── detect_relations_for_cluster: cosine filter ──────────────────────────────

class TestCosineFilter:
    def test_low_similarity_pairs_are_filtered(self, detector):
        """Two orthogonal embeddings → cosine ≈ 0 → filtered out → no LLM call."""
        emb = [[1, 0, 0, 0, 0, 0, 0, 0],   # orthogonal to the next two
               [0, 1, 0, 0, 0, 0, 0, 0]]
        with patch.object(detector, "_analyze_pair") as mock_analyze:
            detector.detect_relations_for_cluster(0, ["c1", "c2"], ["t1", "t2"], emb, [{}, {}])
            mock_analyze.assert_not_called()

    def test_similar_pairs_trigger_llm(self, detector):
        """Two nearly identical embeddings → cosine ≈ 1 → LLM is called."""
        v = [1.0, 0, 0, 0, 0, 0, 0, 0]
        emb = [v, v]  # identical → cosine = 1.0
        with patch.object(detector, "_analyze_pair", return_value=None) as mock_analyze:
            detector.detect_relations_for_cluster(0, ["c1", "c2"], ["t1", "t2"], emb, [{}, {}])
            mock_analyze.assert_called_once()


# ── detect_relations_for_cluster: valid relation ─────────────────────────────

class TestValidRelation:
    def test_llm_relation_is_included_in_output(self, detector):
        v = [1.0, 0, 0, 0, 0, 0, 0, 0]
        emb = [v, v]
        fake_result = {
            "existe": True, "type": "COMPLEMENTAIRE",
            "intensite": "FORTE", "confiance": 0.9,
            "justification": "Lien fort entre les deux contenus"
        }
        with patch.object(detector, "_analyze_pair", return_value=fake_result):
            relations = detector.detect_relations_for_cluster(
                0, ["c1", "c2"], ["t1", "t2"], emb, [{}, {}]
            )
        assert len(relations) == 1
        r = relations[0]
        assert r["chunk_a_id"] == "c1"
        assert r["chunk_b_id"] == "c2"
        assert r["type"] == "COMPLEMENTAIRE"
        assert r["intensite"] == "FORTE"
        assert 0.0 <= r["confiance"] <= 1.0

    def test_relation_not_existing_is_excluded(self, detector):
        v = [1.0, 0, 0, 0, 0, 0, 0, 0]
        emb = [v, v]
        fake_result = {"existe": False, "type": "AUTRE", "intensite": "FAIBLE",
                       "confiance": 0.1, "justification": "Aucune relation"}
        with patch.object(detector, "_analyze_pair", return_value=fake_result):
            relations = detector.detect_relations_for_cluster(
                0, ["c1", "c2"], ["t1", "t2"], emb, [{}, {}]
            )
        assert len(relations) == 0

    def test_none_from_llm_is_excluded(self, detector):
        v = [1.0, 0, 0, 0, 0, 0, 0, 0]
        emb = [v, v]
        with patch.object(detector, "_analyze_pair", return_value=None):
            relations = detector.detect_relations_for_cluster(
                0, ["c1", "c2"], ["t1", "t2"], emb, [{}, {}]
            )
        assert len(relations) == 0


# ── Type and intensite validation ─────────────────────────────────────────────

class TestValidation:
    def _run_with_result(self, detector, result_dict):
        v = [1.0, 0, 0, 0, 0, 0, 0, 0]
        emb = [v, v]
        with patch.object(detector, "_analyze_pair", return_value=result_dict):
            return detector.detect_relations_for_cluster(
                0, ["c1", "c2"], ["t1", "t2"], emb, [{}, {}]
            )

    def test_invalid_type_falls_back_to_autre(self, detector):
        result = {"existe": True, "type": "RANDOM_GARBAGE",
                  "intensite": "FORTE", "confiance": 0.8, "justification": "x"}
        relations = self._run_with_result(detector, result)
        assert relations[0]["type"] == "AUTRE"

    def test_invalid_intensite_falls_back_to_moyenne(self, detector):
        result = {"existe": True, "type": "COMPLEMENTAIRE",
                  "intensite": "INCONNUE", "confiance": 0.8, "justification": "x"}
        relations = self._run_with_result(detector, result)
        assert relations[0]["intensite"] == "MOYENNE"

    def test_confiance_clamped_to_0_1(self, detector):
        result = {"existe": True, "type": "SIMILAIRE",
                  "intensite": "MOYENNE", "confiance": 99.9, "justification": "x"}
        relations = self._run_with_result(detector, result)
        assert relations[0]["confiance"] == 1.0

    def test_confiance_negative_clamped(self, detector):
        result = {"existe": True, "type": "SIMILAIRE",
                  "intensite": "MOYENNE", "confiance": -5.0, "justification": "x"}
        relations = self._run_with_result(detector, result)
        assert relations[0]["confiance"] == 0.0

    def test_justification_truncated_to_500_chars(self, detector):
        long_just = "x" * 1000
        result = {"existe": True, "type": "COMPLEMENTAIRE",
                  "intensite": "FORTE", "confiance": 0.7, "justification": long_just}
        relations = self._run_with_result(detector, result)
        assert len(relations[0]["justification"]) <= 500


# ── _build_prompt ─────────────────────────────────────────────────────────────

class TestBuildPrompt:
    def test_contains_both_texts(self, detector):
        prompt = detector._build_prompt("TextA", {"title": "A"}, "TextB", {"title": "B"})
        assert "TextA" in prompt
        assert "TextB" in prompt

    def test_contains_titles(self, detector):
        prompt = detector._build_prompt("ta", {"title": "DocA"}, "tb", {"title": "DocB"})
        assert "DocA" in prompt
        assert "DocB" in prompt

    def test_text_truncated_at_1500_chars(self, detector):
        long = "x" * 3000
        prompt = detector._build_prompt(long, {}, long, {})
        # The truncated version should appear, not the full 3000-char one
        assert "x" * 1501 not in prompt

    def test_prompt_mentions_json(self, detector):
        prompt = detector._build_prompt("ta", {}, "tb", {})
        assert "JSON" in prompt.upper() or "json" in prompt

    def test_uses_default_title_when_missing(self, detector):
        prompt = detector._build_prompt("ta", {}, "tb", {})
        assert "Document A" in prompt or "Document B" in prompt


# ── Pair limit ────────────────────────────────────────────────────────────────

class TestPairLimit:
    def test_max_pairs_limits_llm_calls(self):
        """With 10 items → 45 pairs, but limit=5 → at most 5 LLM calls."""
        det = RelationDetector(similarity_threshold=0.0, max_pairs_per_cluster=5)
        v = [1.0, 0, 0, 0, 0, 0, 0, 0]
        emb = [v] * 10
        ids = [f"c{i}" for i in range(10)]
        texts = ["t"] * 10
        metas = [{}] * 10

        call_count = []

        def fake_analyze(**kwargs):
            call_count.append(1)
            return {"existe": False, "type": "AUTRE", "intensite": "FAIBLE",
                    "confiance": 0.0, "justification": ""}

        with patch.object(det, "_analyze_pair", side_effect=fake_analyze):
            det.detect_relations_for_cluster(0, ids, texts, emb, metas)

        assert len(call_count) <= 5
