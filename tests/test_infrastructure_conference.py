"""Tests for conference room booking agent."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.infrastructure import store
from app.infrastructure.conference_agent import handle_conference_query
from app.infrastructure import graph_calendar


def test_conference_booking_lists_rooms():
    store.seed_conference_rooms_if_empty()
    with patch("app.infrastructure.conference_agent._classify_sub_intent") as mock_cls:
        mock_cls.return_value = {"sub_intent": "check_availability", "date": "2026-08-12"}
        result = handle_conference_query(
            user_email="employee@ampcus.com",
            query="which conference rooms are available tomorrow?",
            session_id="test-session",
        )
    assert "Available rooms" in result["answer"] or "Conference Room" in result["answer"]


def test_graph_create_booking_simulated_when_no_credentials():
    store.seed_conference_rooms_if_empty()
    from datetime import datetime, timezone

    start = datetime(2026, 8, 12, 14, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 12, 15, 0, tzinfo=timezone.utc)
    result = graph_calendar.create_booking(
        user_email="employee@ampcus.com",
        room_email="ny-room-a@ampcus.com",
        room_name="Conference Room A",
        start=start,
        end=end,
    )
    assert result.get("success")
    assert result.get("simulated")


def test_supervisor_routes_infrastructure_action():
    from app.agents.supervisor import supervise

    result = supervise("print this document", user_role="employee", has_document=True)
    assert result["intent"] == "infrastructure_action"


def test_supervisor_conference_vs_guesthouse():
    from app.agents.supervisor import supervise

    guest = supervise("book the guesthouse for next week", user_role="employee")
    assert guest["intent"] == "reservation_query"

    conf = supervise("book a conference room tomorrow at 2pm", user_role="employee")
    assert conf["intent"] == "infrastructure_action"
