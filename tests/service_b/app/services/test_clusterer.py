# tests/service_b/test_clusterer.py
"""Unit tests for ClusteringService."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../../"))

import pytest
import numpy as np
from services.service_b.app.services.clusterer import ClusteringService


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def service():
    return ClusteringService()


@pytest.fixture
def embeddings_20():
    """20 samples — enough for auto-K."""
    rng = np.random.default_rng(42)
    return rng.random((20, 8)).tolist()


@pytest.fixture
def embeddings_2():
    rng = np.random.default_rng(1)
    return rng.random((2, 8)).tolist()


@pytest.fixture
def embeddings_1():
    rng = np.random.default_rng(2)
    return rng.random((1, 8)).tolist()


@pytest.fixture
def embeddings_3():
    rng = np.random.default_rng(3)
    return rng.random((3, 8)).tolist()


# ── Result schema ─────────────────────────────────────────────────────────────

class TestResultSchema:
    def test_has_required_keys(self, service, embeddings_20):
        result = service.cluster(embeddings_20, method="auto-k")
        assert "labels" in result
        assert "n_clusters" in result
        assert "silhouette_score" in result
        assert "davies_bouldin_score" in result

    def test_labels_count_equals_input_count(self, service, embeddings_20):
        result = service.cluster(embeddings_20)
        assert len(result["labels"]) == len(embeddings_20)

    def test_n_clusters_is_positive_int(self, service, embeddings_20):
        result = service.cluster(embeddings_20)
        assert isinstance(result["n_clusters"], int)
        assert result["n_clusters"] >= 1

    def test_silhouette_in_valid_range(self, service, embeddings_20):
        result = service.cluster(embeddings_20)
        assert -1.0 <= result["silhouette_score"] <= 1.0

    def test_davies_bouldin_non_negative(self, service, embeddings_20):
        result = service.cluster(embeddings_20)
        assert result["davies_bouldin_score"] >= 0.0

    def test_labels_are_integers(self, service, embeddings_20):
        result = service.cluster(embeddings_20)
        for label in result["labels"]:
            assert isinstance(label, int)

    def test_label_range_within_n_clusters(self, service, embeddings_20):
        result = service.cluster(embeddings_20)
        k = result["n_clusters"]
        for label in result["labels"]:
            assert 0 <= label < k


# ── Fewer than 3 samples (degenerate case) ───────────────────────────────────

class TestFewSamples:
    def test_one_sample_returns_single_cluster(self, service, embeddings_1):
        result = service.cluster(embeddings_1)
        assert result["n_clusters"] == 1
        assert result["labels"] == [0]

    def test_two_samples_returns_single_cluster(self, service, embeddings_2):
        result = service.cluster(embeddings_2)
        assert result["n_clusters"] == 1
        assert len(result["labels"]) == 2

    def test_three_samples_does_not_crash(self, service, embeddings_3):
        result = service.cluster(embeddings_3)
        assert len(result["labels"]) == 3

    def test_degenerate_scores_are_zero(self, service, embeddings_1):
        result = service.cluster(embeddings_1)
        assert result["silhouette_score"] == 0.0
        assert result["davies_bouldin_score"] == 0.0


# ── Force-K mode ──────────────────────────────────────────────────────────────

class TestForceK:
    def test_force_k_respected(self, service, embeddings_20):
        result = service.cluster(embeddings_20, force_k=3)
        assert result["n_clusters"] == 3

    def test_force_k_1(self, service, embeddings_20):
        result = service.cluster(embeddings_20, force_k=1)
        assert result["n_clusters"] == 1

    def test_force_k_capped_at_n_minus_1(self, service, embeddings_3):
        """force_k larger than n_samples should be capped."""
        result = service.cluster(embeddings_3, force_k=100)
        assert result["n_clusters"] <= len(embeddings_3)

    def test_force_k_labels_all_valid(self, service, embeddings_20):
        result = service.cluster(embeddings_20, force_k=4)
        k = result["n_clusters"]
        for label in result["labels"]:
            assert 0 <= label < k


# ── Auto-K mode ───────────────────────────────────────────────────────────────

class TestAutoK:
    def test_auto_k_produces_valid_k(self, service, embeddings_20):
        result = service.cluster(embeddings_20, method="auto-k")
        assert result["n_clusters"] >= 2

    def test_custom_k_range(self, service, embeddings_20):
        result = service.cluster(embeddings_20, method="auto-k", k_range=(2, 4))
        # k must be within or close to the range
        assert result["n_clusters"] >= 1

    def test_k_range_min_equals_max(self, service, embeddings_20):
        """k_range with min == max should not crash."""
        result = service.cluster(embeddings_20, method="auto-k", k_range=(3, 3))
        assert result["n_clusters"] >= 1

    def test_deterministic_with_same_seed(self, service):
        rng = np.random.default_rng(99)
        emb = rng.random((15, 8)).tolist()
        r1 = service.cluster(emb, force_k=3)
        r2 = service.cluster(emb, force_k=3)
        assert r1["labels"] == r2["labels"]


# ── Unknown method fallback ───────────────────────────────────────────────────

class TestUnknownMethod:
    def test_unknown_method_does_not_raise(self, service, embeddings_20):
        result = service.cluster(embeddings_20, method="sqrt")
        assert "labels" in result
        assert len(result["labels"]) == len(embeddings_20)
