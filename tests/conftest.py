# tests/conftest.py
"""Shared fixtures for all tests."""

import pytest
import numpy as np


@pytest.fixture
def sample_embeddings():
    """Generate deterministic sample embeddings (384-dim like MiniLM)."""
    rng = np.random.default_rng(42)
    return rng.random((20, 384)).tolist()


@pytest.fixture
def small_embeddings():
    """Small set of embeddings for edge cases."""
    rng = np.random.default_rng(0)
    return rng.random((3, 8)).tolist()
