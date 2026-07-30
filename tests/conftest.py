"""Shared fixtures for API integration tests (isolated Chroma + tickets)."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

# Sentence-transformers + Starlette TestClient threads can AV on Windows;
# keep embedding work single-threaded in tests.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("TORCH_NUM_THREADS", "1")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """
    Fresh app with:
    - isolated Chroma + tickets under tmp_path
    - LLM_PROVIDER=anthropic without key → heuristic classify + offline excerpts
    - semantic cache enabled for hit/miss coverage
    """
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(chroma_dir))
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("SEMANTIC_CACHE_ENABLED", "true")
    monkeypatch.setenv("SEMANTIC_CACHE_THRESHOLD", "0.70")
    monkeypatch.setenv("INGEST_DEDUP_MAX_DISTANCE", "0.45")
    monkeypatch.setenv("RETRIEVAL_MAX_DISTANCE", "1.15")
    monkeypatch.setenv("REDIS_URL", "")

    from app.config import get_settings

    get_settings.cache_clear()

    import app.agents.graph as graph_mod
    import app.analytics.stats as stats_mod
    import app.cache.redis_cache as redis_mod
    import app.cache.semantic_cache as sem_mod
    import app.rag.chroma_store as chroma_mod

    graph_mod._compiled = None
    chroma_mod._store = None
    sem_mod._semantic = None
    redis_mod._cache = None
    stats_mod.reset_stats()

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client

    graph_mod._compiled = None
    chroma_mod._store = None
    sem_mod._semantic = None
    redis_mod._cache = None
    get_settings.cache_clear()
