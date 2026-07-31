"""Unit tests for escalation / high-severity ticket notifications."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.tickets.notify import (
    build_opened_admin_email,
    build_opened_employee_email,
    build_reminder_admin_email,
    build_resolved_employee_email,
    notify_ticket_opened,
    notify_ticket_resolved,
    process_escalation_reminders,
)
from app.tickets.store import (
    TICKET_TYPE_ESCALATION,
    create_ticket,
    get_ticket,
    list_due_escalation_reminders,
    update_ticket,
)


@pytest.fixture()
def tickets_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("USERS_PATH", str(tmp_path / "users.json"))
    monkeypatch.setenv("ADMIN_EMAIL", "admin@ampcus.com")
    monkeypatch.setenv("ESCALATION_REMINDER_HOURS", "2")
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("APP_BASE_URL", "http://127.0.0.1:8080")
    get_settings.cache_clear()
    (tmp_path / "chroma").mkdir(parents=True, exist_ok=True)
    from app.auth.users import create_user

    create_user(
        email="admin@ampcus.com",
        password="ChangeMeAdmin1!",
        role="admin",
        name="Admin",
    )
    create_user(
        email="employee@ampcus.com",
        password="EmployeePass12!",
        role="employee",
        name="Emp",
    )
    yield
    get_settings.cache_clear()


def test_email_templates_include_ticket_fields(tickets_env):
    ticket = {
        "id": "t-1",
        "ticket_type": "escalation",
        "status": "open",
        "department": "it",
        "severity": "high",
        "created_by_email": "employee@ampcus.com",
        "created_at": "2026-01-01T00:00:00+00:00",
        "reason": "High-severity IT",
        "question": "Production outage affecting payroll SSO",
    }
    _, admin_body = build_opened_admin_email(ticket)
    assert "t-1" in admin_body
    assert "payroll SSO" in admin_body
    _, emp_body = build_opened_employee_email(ticket)
    assert "escalated" in emp_body.lower()
    _, rem_body = build_reminder_admin_email(ticket)
    assert "unresolved" in rem_body.lower()
    _, sol_body = build_resolved_employee_email(ticket, solution="Reset MFA then retry SSO")
    assert "Reset MFA" in sol_body


def test_reminder_eligibility_and_once(tickets_env, monkeypatch):
    sent: list[tuple[str, str]] = []

    def _capture(*, to, subject, body):
        sent.append((to, subject))
        return False

    monkeypatch.setattr("app.tickets.notify.send_email", _capture)

    ticket = create_ticket(
        "VPN outage company-wide",
        "vpn outage",
        "High-severity IT",
        ticket_type=TICKET_TYPE_ESCALATION,
        department="it",
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

    now = datetime.now(timezone.utc)
    assert len(list_due_escalation_reminders(now=now, hours=2)) == 1
    assert process_escalation_reminders(now=now, hours=2) == 1
    assert get_ticket(ticket["id"])["reminder_sent_at"]
    assert any("Reminder" in s for _, s in sent)
    sent.clear()
    assert process_escalation_reminders(now=now, hours=2) == 0


def test_notify_opened_and_resolved_idempotent(tickets_env, monkeypatch):
    sent: list[tuple[str, str]] = []

    def _capture(*, to, subject, body):
        sent.append((to, subject))
        return False

    monkeypatch.setattr("app.tickets.notify.send_email", _capture)

    ticket = create_ticket(
        "Suspected harassment complaint",
        "harassment",
        "High-severity HR",
        ticket_type=TICKET_TYPE_ESCALATION,
        department="hr",
        severity="high",
        created_by_email="employee@ampcus.com",
    )
    notify_ticket_opened(ticket)
    first = len(sent)
    assert first >= 2  # admin + employee
    notify_ticket_opened(get_ticket(ticket["id"]))
    assert len(sent) == first  # idempotent

    resolved = update_ticket(
        ticket["id"],
        status="resolved",
        admin_notes="HR will schedule a confidential call.",
    )
    notify_ticket_resolved(resolved, solution="HR will schedule a confidential call.")
    mid = len(sent)
    assert mid == first + 1
    notify_ticket_resolved(get_ticket(ticket["id"]), solution="again")
    assert len(sent) == mid


def test_assigned_still_due_for_reminder(tickets_env):
    ticket = create_ticket(
        "Data retention legal hold",
        "legal hold",
        "High-severity LEGAL",
        ticket_type=TICKET_TYPE_ESCALATION,
        department="legal",
        severity="high",
        created_by_email="employee@ampcus.com",
    )
    old = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    from app.tickets import store as store_mod

    with store_mod._lock:
        tickets = store_mod._read_all()
        for t in tickets:
            if t["id"] == ticket["id"]:
                t["created_at"] = old
                t["status"] = "assigned"
        store_mod._write_all(tickets)

    due = list_due_escalation_reminders(now=datetime.now(timezone.utc), hours=2)
    assert any(t["id"] == ticket["id"] for t in due)
