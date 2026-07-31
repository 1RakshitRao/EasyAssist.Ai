"""Unit tests for BoardMonitorAgent."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.agents.board_monitor import BoardMonitorAgent, run_board_monitor_once
from app.config import get_settings
from app.tickets.store import TICKET_TYPE_ESCALATION, create_ticket, get_ticket


@pytest.fixture()
def board_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("USERS_PATH", str(tmp_path / "users.json"))
    monkeypatch.setenv("ADMIN_EMAIL", "admin@ampcus.com")
    monkeypatch.setenv("ESCALATION_REMINDER_HOURS", "2")
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    (tmp_path / "chroma").mkdir(parents=True, exist_ok=True)
    from app.auth.users import create_user

    create_user(
        email="admin@ampcus.com",
        password="ChangeMeAdmin1!",
        role="admin",
        name="Admin",
    )
    yield
    get_settings.cache_clear()


def test_board_monitor_reminds_unresolved(board_env, monkeypatch):
    sent = []

    def _capture(*, to, subject, body):
        sent.append({"to": to, "subject": subject})
        return False

    monkeypatch.setattr("app.tickets.notify.send_email", _capture)

    ticket = create_ticket(
        "Breach response needed",
        "breach",
        "High-severity LEGAL",
        ticket_type=TICKET_TYPE_ESCALATION,
        department="legal",
        severity="high",
        created_by_email="employee@ampcus.com",
    )
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    from app.tickets import store as store_mod

    with store_mod._lock:
        tickets = store_mod._read_all()
        for t in tickets:
            if t["id"] == ticket["id"]:
                t["created_at"] = old
        store_mod._write_all(tickets)

    agent = BoardMonitorAgent()
    assert len(agent.unresolved_past_sla()) == 1
    assert run_board_monitor_once() == 1
    assert get_ticket(ticket["id"])["reminder_sent_at"]
    assert any("Reminder" in m["subject"] for m in sent)
    assert run_board_monitor_once() == 0
