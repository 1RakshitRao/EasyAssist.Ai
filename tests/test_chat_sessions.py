"""Chat session store + API + answer history wiring."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.agents.answer import generate_answer
from app.audit.db import init_audit_db
from app.chat.store import (
    CHAT_CONTEXT_LIMIT,
    delete_session,
    ensure_session,
    get_messages,
    list_sessions,
    load_history,
    save_message,
    trim_title,
)
from app.config import get_settings
from app.llm.client import LLMResult


@pytest.fixture()
def chat_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    get_settings.cache_clear()
    init_audit_db()
    yield
    get_settings.cache_clear()


def test_trim_title():
    assert trim_title("short") == "short"
    long = "How many days of annual leave do I get as a full time employee?"
    t = trim_title(long, max_len=50)
    assert len(t) <= 50
    assert t.endswith("…")


def test_chat_store_crud_and_history_window(chat_db):
    email = "rakshit@ampcus.com"
    sid = ensure_session(None, email, title_seed="How many leave days?")
    assert sid.startswith("sess_")

    sessions = list_sessions(email)
    assert len(sessions) == 1
    assert sessions[0]["title"].startswith("How many leave")

    for i in range(5):
        save_message(session_id=sid, user_email=email, role="user", content=f"user-{i}")
        save_message(
            session_id=sid,
            user_email=email,
            role="assistant",
            content=f"bot-{i}",
            department="hr",
            cost_usd=0.01,
        )

    hist = load_history(sid, email, limit=CHAT_CONTEXT_LIMIT)
    assert len(hist) == CHAT_CONTEXT_LIMIT
    assert hist[0]["role"] == "user"
    assert hist[-1]["role"] == "assistant"
    # Last 6 of 10 messages: user-2..bot-4
    assert hist[0]["content"] == "user-2"
    assert hist[-1]["content"] == "bot-4"

    full = get_messages(sid, email)
    assert full is not None
    assert len(full) == 10

    other = get_messages(sid, "other@ampcus.com")
    assert other is None

    assert delete_session(sid, email) is True
    assert list_sessions(email) == []
    assert delete_session(sid, email) is False


def test_ensure_session_rejects_foreign_owner(chat_db):
    sid = ensure_session("sess_owned", "a@ampcus.com", title_seed="hi")
    with pytest.raises(PermissionError):
        ensure_session(sid, "b@ampcus.com", title_seed="nope")


def test_generate_answer_passes_history_to_complete(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "grok")
    monkeypatch.setenv("XAI_API_KEY", "test-key")
    get_settings.cache_clear()
    captured = {}

    def fake_complete(**kwargs):
        captured["messages"] = kwargs.get("messages")
        return LLMResult(
            text="Sick leave is 10 days.",
            model="test",
            token_usage={"input_tokens": 10, "output_tokens": 5},
            provider="grok",
        )

    history = [
        {"role": "user", "content": "how many leave days?"},
        {"role": "assistant", "content": "20 days annual."},
        {"role": "user", "content": "what about sick leave?"},
    ]
    chunks = [{"title": "HR Leave", "content": "Sick leave is 10 days per year."}]

    with patch("app.agents.answer.complete", side_effect=fake_complete):
        result = generate_answer(
            question="what about sick leave?",
            chunks=chunks,
            conversation_history=history[:2],  # prior only
        )

    assert result["answer"] == "Sick leave is 10 days."
    msgs = captured["messages"]
    assert msgs[0] == history[0]
    assert msgs[1] == history[1]
    assert msgs[-1]["role"] == "user"
    assert "Question: what about sick leave?" in msgs[-1]["content"]
    assert "Sick leave is 10 days" in msgs[-1]["content"]
    get_settings.cache_clear()


def test_sessions_api_and_two_turn_query(client, employee_headers, monkeypatch):
    # Avoid slow/fragile scorer LLM in this path
    monkeypatch.setattr(
        "app.api.routes_query.score_prompt",
        lambda q: {"score": 8, "issues": [], "improved_query": None, "reason": "test"},
    )

    created = client.post("/sessions", headers=employee_headers)
    assert created.status_code == 200, created.text
    session_id = created.json()["session_id"]
    assert session_id.startswith("sess_")

    r1 = client.post(
        "/query",
        headers=employee_headers,
        json={
            "question": "How many annual leave days do full-time employees get?",
            "session_id": session_id,
            "model_preference": "auto",
        },
    )
    assert r1.status_code == 200, r1.text
    body1 = r1.json()
    assert body1["session_id"] == session_id
    assert body1["answer"]

    r2 = client.post(
        "/query",
        headers=employee_headers,
        json={
            "question": "What about sick leave?",
            "session_id": session_id,
            "model_preference": "auto",
        },
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["session_id"] == session_id

    listed = client.get("/sessions", headers=employee_headers)
    assert listed.status_code == 200
    sessions = listed.json()
    assert any(s["session_id"] == session_id for s in sessions)
    assert any(s["message_count"] >= 4 for s in sessions if s["session_id"] == session_id)

    msgs = client.get(f"/sessions/{session_id}/messages", headers=employee_headers)
    assert msgs.status_code == 200
    thread = msgs.json()
    assert len(thread) >= 4
    assert thread[0]["role"] == "user"
    assert thread[1]["role"] == "assistant"

    # Ownership: admin cannot read employee's session
    admin_login = client.post(
        "/auth/login",
        json={"email": "admin@ampcus.com", "password": "ChangeMeAdmin1!"},
    )
    admin_h = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}
    denied = client.get(f"/sessions/{session_id}/messages", headers=admin_h)
    assert denied.status_code == 404

    deleted = client.delete(f"/sessions/{session_id}", headers=employee_headers)
    assert deleted.status_code == 200
    gone = client.get(f"/sessions/{session_id}/messages", headers=employee_headers)
    assert gone.status_code == 404


def test_semantic_cache_still_works_on_fresh_session(client, employee_headers, monkeypatch):
    monkeypatch.setattr(
        "app.api.routes_query.score_prompt",
        lambda q: {"score": 8, "issues": [], "improved_query": None, "reason": "test"},
    )
    q = "How many PTO days do Ampcus full-time employees receive annually?"
    sid1 = "sess_cache_fresh_1"
    r1 = client.post(
        "/query",
        headers=employee_headers,
        json={"question": q, "session_id": sid1},
    )
    assert r1.status_code == 200, r1.text
    # Second turn on SAME session should skip cache (has prior history)
    r2 = client.post(
        "/query",
        headers=employee_headers,
        json={"question": "and sick leave?", "session_id": sid1},
    )
    assert r2.status_code == 200
    assert r2.json().get("cached") is False

    # Brand-new session with same first question may hit cache
    sid2 = "sess_cache_fresh_2"
    r3 = client.post(
        "/query",
        headers=employee_headers,
        json={"question": q, "session_id": sid2},
    )
    assert r3.status_code == 200, r3.text
    # Cache hit only when first turn stored a cacheable answer
    if r1.json().get("context_used") and r1.json().get("severity") == "routine":
        assert r3.json().get("cached") is True
