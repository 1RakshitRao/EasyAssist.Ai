"""KB miss confirm-before-ticket flow tests."""

from __future__ import annotations

from app.agents.answer_no_context import (
    answer_no_context_node,
    build_no_context_answer,
    build_pending_ticket_payload,
)
from app.chat.pending_ticket import clear_pending, get_pending, save_pending


def test_build_no_context_answer_includes_contact():
    text = build_no_context_answer(department="hr", severity="routine")
    assert "knowledge base" in text.lower()
    assert "hr@ampcus.com" in text
    assert "support ticket" in text.lower()


def test_build_no_context_answer_high_severity_urgency():
    text = build_no_context_answer(department="legal", severity="high")
    assert "time-sensitive" in text.lower()


def test_answer_no_context_node_sets_pending():
    result = answer_no_context_node(
        {
            "query": "cafeteria sushi?",
            "normalized_query": "cafeteria sushi",
            "department": "unknown",
            "severity": "routine",
            "attempted_depts": ["hr", "it", "compliance", "legal"],
            "chunks": [],
        }
    )
    assert result["pending_ticket_confirmation"] is True
    assert result["model_used"] == "no_context"
    assert result["ticket_id"] is None
    assert result["pending_ticket_payload"]["ticket_type"] == "unknown"


def test_pending_payload_escalation_type():
    payload = build_pending_ticket_payload(
        {
            "query": "data breach",
            "normalized_query": "data breach",
            "department": "legal",
            "severity": "high",
            "escalated": True,
            "chunks": [{"content": "x", "title": "t"}],
        }
    )
    assert payload["ticket_type"] == "escalation"
    assert payload["department"] == "legal"
    assert payload["severity"] == "high"


def test_decline_ticket_clears_pending(client, admin_headers):
    miss = client.post(
        "/query",
        headers=admin_headers,
        json={"question": "What is the cafeteria sushi menu this Friday?"},
    )
    assert miss.status_code == 200
    data = miss.json()
    session_id = data["session_id"]
    assert data["pending_ticket_confirmation"] is True

    decline = client.post(
        "/query",
        headers=admin_headers,
        json={
            "question": "(confirm)",
            "confirm_ticket": False,
            "session_id": session_id,
        },
    )
    assert decline.status_code == 200
    declined = decline.json()
    assert declined["ticket_id"] is None
    assert declined["pending_ticket_confirmation"] is False
    assert "no problem" in declined["answer"].lower()

    tickets = client.get(
        "/tickets",
        headers=admin_headers,
        params={"status": "open", "ticket_type": "unknown"},
    )
    assert tickets.status_code == 200
    assert not any(
        t["question"] == "What is the cafeteria sushi menu this Friday?"
        for t in tickets.json()
    )


def test_new_question_clears_pending_implicit_decline(client, admin_headers):
    miss = client.post(
        "/query",
        headers=admin_headers,
        json={"question": "What is the cafeteria sushi menu this Friday?"},
    )
    session_id = miss.json()["session_id"]

    follow = client.post(
        "/query",
        headers=admin_headers,
        json={
            "question": "How do I reset my password?",
            "session_id": session_id,
        },
    )
    assert follow.status_code == 200
    assert follow.json()["department"] == "it"

    confirm = client.post(
        "/query",
        headers=admin_headers,
        json={
            "question": "(confirm)",
            "confirm_ticket": True,
            "session_id": session_id,
        },
    )
    assert confirm.status_code == 400


def test_pending_ticket_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    from app.config import get_settings

    get_settings.cache_clear()
    from app.chat.store import ensure_session

    sid = ensure_session(None, "admin@ampcus.com", title_seed="test")
    payload = {"question": "q", "department": "unknown", "ticket_type": "unknown"}
    save_pending(sid, payload)
    assert get_pending(sid) == payload
    clear_pending(sid)
    assert get_pending(sid) is None
    get_settings.cache_clear()
