"""Tests for structured query trace logging."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.graph import reset_graph, run_pipeline
from app.audit.db import connect, init_audit_db
from app.audit.query_trace import QueryTracer, set_tracer
from app.audit.store import append_event, get_query_trace
from app.llm.client import LLMResult


@pytest.fixture()
def trace_db(tmp_path, monkeypatch):
    db_path = tmp_path / "audit.db"
    monkeypatch.setenv("AUDIT_DB_PATH", str(db_path))
    from app.config import get_settings

    get_settings.cache_clear()
    init_audit_db()
    yield db_path
    get_settings.cache_clear()


def test_tracer_accumulates_steps_and_persists(trace_db):
    tracer = QueryTracer(
        user_id="u1",
        user_email="emp@ampcus.com",
        query="test question",
        session_id="sess-1",
    )
    tracer.received(role="employee", session_id="sess-1")
    tracer.supervisor_classified("helpdesk_query", "high", "test")
    tracer.supervisor_routed("semantic_cache_check")
    tracer.complete(model_used="test-model", node="answer", intent="helpdesk_query")
    tracer.save()

    assert len(tracer.steps) >= 4
    assert tracer.summary["intent"] == "helpdesk_query"
    assert tracer.summary["duration_ms"] >= 0

    stored = get_query_trace(tracer.query_id)
    assert stored is not None
    assert stored["user_email"] == "emp@ampcus.com"
    assert stored["query"] == "test question"
    assert stored["intent"] == "helpdesk_query"
    assert len(stored["steps"]) == len(tracer.steps)
    events = {s.get("event") for s in stored["steps"]}
    assert "query_received" in events
    assert "supervisor_classified" in events
    assert "complete" in events


def test_audit_event_links_query_id(trace_db):
    tracer = QueryTracer(
        user_id="u1",
        user_email="emp@ampcus.com",
        query="linked query",
        session_id="sess-2",
    )
    tracer.received(role="employee")
    tracer.complete(model_used="none", node="block", intent="restricted")
    tracer.save()

    append_event(
        {
            "user_id": "u1",
            "user_email": "emp@ampcus.com",
            "query": "linked query",
            "intent": "restricted",
            "query_id": tracer.query_id,
        }
    )

    with connect() as conn:
        row = conn.execute(
            "SELECT query_id FROM audit_events WHERE query_id = ?",
            (tracer.query_id,),
        ).fetchone()
    assert row is not None
    assert row["query_id"] == tracer.query_id


def _supervisor_payload(intent: str) -> MagicMock:
    body = {
        "intent": intent,
        "confidence": "high",
        "reason": f"route {intent}",
        "document_operation": None,
    }
    return MagicMock(
        return_value=LLMResult(
            text=json.dumps(body),
            model="test",
            token_usage={},
            provider="test",
        )
    )


def test_reservation_path_trace_integration(trace_db, monkeypatch):
    """Pipeline reservation route emits supervisor + reservation trace events."""
    from app.config import get_settings

    monkeypatch.setenv("SEMANTIC_CACHE_ENABLED", "false")
    get_settings.cache_clear()
    reset_graph()

    tracer = QueryTracer(
        user_id="u1",
        user_email="emp@ampcus.com",
        query="is the guesthouse available next week?",
        session_id="sess-res",
    )
    set_tracer(tracer)

    with patch("app.agents.supervisor.complete", _supervisor_payload("reservation_query")):
        with patch(
            "app.reservations.reservation_agent.detect_sub_intent",
            return_value={"sub_intent": "check_availability", "guesthouse_name": "4656"},
        ):
            from app.reservations import store

            store.seed_guesthouses()
            result = run_pipeline(
                query="is the guesthouse available next week?",
                normalized_query="is the guesthouse available next week?",
                user_email="emp@ampcus.com",
                session_id="sess-res",
                tracer=tracer,
            )

    tracer.complete(
        model_used=result.get("model_used") or "reservation_agent",
        node="reservation",
        intent=result.get("intent") or "reservation_query",
    )
    tracer.save()

    events = [s.get("event") for s in tracer.steps]
    agents = [s.get("agent") for s in tracer.steps]
    assert "supervisor_classified" in events
    assert "supervisor_routed" in events
    assert "RESERVATION" in agents
    assert any(
        s.get("event") == "agent_step" and "Sub-intent" in (s.get("message") or "")
        for s in tracer.steps
    )
    assert "complete" in events

    stored = get_query_trace(tracer.query_id)
    assert stored["target_node"] == "reservation"
    assert stored["intent"] == "reservation_query"
