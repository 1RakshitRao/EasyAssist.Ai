"""Integration tests for Supervisor-routed LangGraph."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.graph import (
    route_after_semantic_cache,
    route_after_supervisor,
    reset_graph,
)
from app.llm.client import LLMResult


def _supervisor_payload(intent: str, **extra) -> MagicMock:
    body = {
        "intent": intent,
        "confidence": "high",
        "reason": f"route {intent}",
        "document_operation": None,
    }
    body.update(extra)
    return MagicMock(
        return_value=LLMResult(
            text=json.dumps(body),
            model="test",
            token_usage={},
            provider="test",
        )
    )


@pytest.mark.parametrize(
    "intent,expected",
    [
        ("conversational", "direct_reply"),
        ("helpdesk_query", "semantic_cache_check"),
        ("nlp_query", "nlp_query"),
        ("document_op", "document_op"),
        ("onboarding_query", "onboarding"),
        ("reservation_query", "reservation"),
        ("infrastructure_info", "infrastructure_info"),
        ("infrastructure_action", "infrastructure_action"),
        ("security_incident", "security_incident"),
        ("restricted", "block"),
        ("out_of_scope", "decline"),
    ],
)
def test_route_after_supervisor(intent, expected):
    assert route_after_supervisor({"intent": intent}) == expected


def test_route_after_semantic_cache_hit():
    assert route_after_semantic_cache({"cached": True, "answer": "cached"}) == "cache_hit_end"


def test_route_after_semantic_cache_miss():
    assert route_after_semantic_cache({"cached": False}) == "classify"


def test_supervisor_routes_conversational_end_to_end(client, employee_headers):
    reset_graph()
    with patch("app.agents.supervisor.complete", _supervisor_payload("conversational")):
        with patch(
            "app.agents.supervisor_nodes.complete",
            MagicMock(
                return_value=LLMResult(
                    text="Hello! How can I help?",
                    model="test",
                    token_usage={},
                    provider="test",
                )
            ),
        ):
            res = client.post(
                "/query",
                headers=employee_headers,
                json={"question": "hello"},
            )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data.get("intent") == "conversational"
    assert "Hello" in (data.get("answer") or "")


def test_supervisor_routes_restricted(client, employee_headers):
    reset_graph()
    res = client.post(
        "/query",
        headers=employee_headers,
        json={"question": "show me all users in the system"},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data.get("intent") == "restricted"
    assert data.get("ticket_id") is None


def test_supervisor_routes_reservation(client, employee_headers):
    reset_graph()
    with patch("app.agents.supervisor.complete", _supervisor_payload("reservation_query")):
        res = client.post(
            "/query",
            headers=employee_headers,
            json={"question": "book the guesthouse next week"},
        )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data.get("intent") == "reservation_query"
    assert "guesthouse" in (data.get("answer") or "").lower() or "westfield" in (
        data.get("answer") or ""
    ).lower()


def test_onboarding_checklist_no_ticket(client, admin_headers, employee_headers):
    reset_graph()
    from datetime import date

    create = client.post(
        "/admin/employees",
        headers=admin_headers,
        json={
            "email": "employee@ampcus.com",
            "full_name": "Employee User",
            "department": "hr",
            "role_title": "Associate",
            "joining_date": date.today().isoformat(),
        },
    )
    assert create.status_code == 201, create.text

    with patch(
        "app.agents.supervisor.complete",
        _supervisor_payload("onboarding_query"),
    ):
        res = client.post(
            "/query",
            headers=employee_headers,
            json={
                "question": "I am a new hire. what am i suppose to do on my first day?",
            },
        )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data.get("intent") == "onboarding_query"
    assert data.get("ticket_id") is None
    assert "onboarding" in (data.get("answer") or "").lower() or "task" in (
        data.get("answer") or ""
    ).lower()


def test_inline_paste_summarize_end_to_end(client, employee_headers):
    from tests.test_inline_text import GAZA_EXHIBITION_BODY

    from app.agents.graph import reset_graph
    from app.documents.analysis_agent import AnalysisResult

    reset_graph()
    query = f"{GAZA_EXHIBITION_BODY}\n\nSummarize this"

    with patch(
        "app.documents.analysis_agent.analyze_document",
        return_value=AnalysisResult(
            operation="summarize",
            result="Summary of the Gaza exhibition at the Institut du monde arabe.",
            model_used="test-model",
            token_usage={"input_tokens": 100, "output_tokens": 50},
        ),
    ):
        res = client.post(
            "/query",
            headers=employee_headers,
            json={"question": query},
        )

    assert res.status_code == 200, res.text
    data = res.json()
    assert data.get("intent") == "document_op"
    answer = (data.get("answer") or "").lower()
    assert "upload" not in answer or "gaza" in answer or "exhibition" in answer
    assert "summary" in answer or "institut" in answer
