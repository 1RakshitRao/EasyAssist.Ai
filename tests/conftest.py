"""Shared fixtures for API integration tests (isolated Chroma + tickets + auth)."""

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
    - isolated Chroma + tickets + users under tmp_path
    - LLM_PROVIDER=anthropic without key → heuristic classify + offline excerpts
    - bootstrap admin from env
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
    monkeypatch.setenv("ADMIN_EMAIL", "admin@ampcus.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "ChangeMeAdmin1!")
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("USERS_PATH", str(tmp_path / "users.json"))
    monkeypatch.setenv("PROMPT_SCORE_WINDOW", "10")
    monkeypatch.setenv("PROMPT_SCORE_RESTRICT_AVG", "4.0")
    monkeypatch.setenv("PROMPT_TRAINING_GRACE_DAYS", "7")
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("JWT_SECRET", "test-secret-ampcus-helpdesk")
    monkeypatch.setenv("ESCALATION_REMINDER_HOURS", "2")
    monkeypatch.setenv("ESCALATION_REMINDER_POLL_SECONDS", "3600")
    monkeypatch.setenv("APP_BASE_URL", "http://127.0.0.1:8080")

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


@pytest.fixture()
def admin_headers(client):
    res = client.post(
        "/auth/login",
        json={"email": "admin@ampcus.com", "password": "ChangeMeAdmin1!"},
    )
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def agent_headers(client, admin_headers):
    created = client.post(
        "/auth/users",
        headers=admin_headers,
        json={
            "email": "agent@ampcus.com",
            "password": "AgentPass12!",
            "role": "agent",
            "name": "Agent User",
        },
    )
    assert created.status_code == 201, created.text
    res = client.post(
        "/auth/login",
        json={"email": "agent@ampcus.com", "password": "AgentPass12!"},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture()
def employee_headers(client, admin_headers):
    created = client.post(
        "/auth/users",
        headers=admin_headers,
        json={
            "email": "employee@ampcus.com",
            "password": "EmployeePass12!",
            "role": "employee",
            "name": "Employee User",
        },
    )
    assert created.status_code == 201, created.text
    res = client.post(
        "/auth/login",
        json={"email": "employee@ampcus.com", "password": "EmployeePass12!"},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def confirm_pending_ticket(client, headers, query_response: dict) -> dict:
    """Confirm a pending KB-miss / escalation ticket from a prior /query response."""
    session_id = query_response.get("session_id")
    assert session_id, "query response missing session_id"
    res = client.post(
        "/query",
        headers=headers,
        json={
            "question": "(confirm)",
            "confirm_ticket": True,
            "session_id": session_id,
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data.get("ticket_id"), data
    return data
