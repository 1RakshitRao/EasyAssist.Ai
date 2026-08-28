"""Tests for security incident routing and responses."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.graph import reset_graph, route_after_supervisor, run_pipeline
from app.agents.security_incident import is_security_incident
from app.agents.supervisor import supervise
from app.llm.client import LLMResult


SECURITY_QUERY = (
    "I think there's been unauthorized access to my work account "
    "and some files may have been compromised."
)


def test_is_security_incident_detects_victim_report():
    assert is_security_incident(SECURITY_QUERY) is True


def test_is_security_incident_not_policy_question():
    assert (
        is_security_incident(
            "What does unauthorized access mean in the acceptable use policy?"
        )
        is False
    )


def test_supervise_routes_security_incident_before_llm():
    with patch("app.agents.supervisor.complete") as mock_complete:
        result = supervise(SECURITY_QUERY, user_role="employee")
        mock_complete.assert_not_called()
    assert result["intent"] == "security_incident"


def test_security_incident_overrides_restricted_llm():
    with patch(
        "app.agents.supervisor.complete",
        MagicMock(
            return_value=LLMResult(
                text=json.dumps(
                    {
                        "intent": "restricted",
                        "confidence": "high",
                        "reason": "misclassified",
                        "document_operation": None,
                    }
                ),
                model="test",
                token_usage={},
                provider="test",
            )
        ),
    ):
        result = supervise(SECURITY_QUERY, user_role="employee")
    assert result["intent"] == "security_incident"


def test_route_after_supervisor_security_incident():
    assert route_after_supervisor({"intent": "security_incident"}) == "security_incident"


def test_security_incident_not_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    reset_graph()

    with patch("app.agents.supervisor.complete") as mock_supervisor_llm:
        result = run_pipeline(
            query=SECURITY_QUERY,
            normalized_query=SECURITY_QUERY.lower(),
            user_email="emp@ampcus.com",
            user_role="employee",
            session_id="sec-test-001",
        )
        mock_supervisor_llm.assert_not_called()

    answer = (result.get("answer") or "").lower()
    assert "can't help" not in answer
    assert "not able to help" not in answer
    assert result.get("severity") == "high"
    assert result.get("escalated") is True
    assert result.get("ticket_id")
    assert "security incident" in answer or "immediate steps" in answer
