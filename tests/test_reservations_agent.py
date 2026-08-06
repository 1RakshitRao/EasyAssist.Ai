"""Reservation agent sub-intent and handler tests."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.config import get_settings
from app.reservations import reservation_agent, store


@pytest.fixture()
def reservation_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    get_settings.cache_clear()
    from app.audit.db import init_audit_db

    init_audit_db()
    store.seed_guesthouses()
    yield
    get_settings.cache_clear()


def test_keyword_sub_intent_availability():
    parsed = reservation_agent._keyword_sub_intent("show availability next week")
    assert parsed["sub_intent"] == "check_availability"


def test_show_details_lists_guesthouses(reservation_db):
    result = reservation_agent.handle_reservation_query(
        user_email="emp@ampcus.com",
        query="tell me about the guesthouse",
    )
    assert "4656" in result["answer"] or "Westfield" in result["answer"]


def test_list_empty(reservation_db):
    result = reservation_agent.handle_reservation_query(
        user_email="emp@ampcus.com",
        query="my reservations",
    )
    assert "no upcoming" in result["answer"].lower()


def test_cancel_48h_message(reservation_db):
    room = store.get_all_rooms()[0]
    checkin = (date.today() + timedelta(days=1)).isoformat()
    checkout = (date.today() + timedelta(days=3)).isoformat()
    res = store.create_reservation("emp@ampcus.com", room["id"], checkin, checkout, "Other")
    store.approve_reservation(res["id"], "hr@ampcus.com")
    result = reservation_agent.handle_reservation_query(
        user_email="emp@ampcus.com",
        query="cancel my reservation",
        session_id="sess-test",
    )
    assert "48 hours" in result["answer"] or "contact hr" in result["answer"].lower()


def test_availability_returns_calendar(reservation_db):
    with patch.object(
        reservation_agent,
        "detect_sub_intent",
        return_value={"sub_intent": "check_availability", "guesthouse_name": "4656"},
    ):
        result = reservation_agent.handle_reservation_query(
            user_email="emp@ampcus.com",
            query="availability",
        )
    assert result.get("reservation_calendar")
    assert result["reservation_calendar"]["guesthouse_name"]
    assert "calendar" in result["answer"].lower() or "select" in result["answer"].lower()
