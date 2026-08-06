"""Integration tests for escalation open / assign / resolve email hooks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.tickets.store import get_ticket, list_tickets
from tests.conftest import confirm_pending_ticket


@pytest.fixture()
def capture_mail(monkeypatch):
    sent: list[dict] = []

    def _capture(*, to, subject, body):
        sent.append({"to": to, "subject": subject, "body": body})
        return False

    monkeypatch.setattr("app.tickets.notify.send_email", _capture)
    return sent


def _query_breach(client, headers):
    res = client.post(
        "/query",
        headers=headers,
        json={
            "question": "I think we had a customer data breach — what should I do legally?"
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    if not data.get("escalated"):
        res = client.post(
            "/query",
            headers=headers,
            json={
                "question": (
                    "I think we had a customer data breach — what should I do?"
                )
            },
        )
        assert res.status_code == 200
        data = res.json()
    return data


def test_high_it_creates_escalation_and_emails(client, employee_headers, capture_mail):
    res = client.post(
        "/query",
        headers=employee_headers,
        json={
            "question": (
                "URGENT company-wide VPN and SSO outage — production is down "
                "and I need emergency IT escalation now"
            )
        },
    )
    assert res.status_code == 200, res.text
    data = res.json()
    if not data.get("escalated"):
        data = _query_breach(client, employee_headers)

    assert data.get("escalated") is True
    assert data.get("pending_ticket_confirmation") is True
    confirmed = confirm_pending_ticket(client, employee_headers, data)
    ticket = get_ticket(confirmed["ticket_id"])
    assert ticket is not None
    assert ticket["ticket_type"] == "escalation"
    assert ticket.get("admin_notified_at")
    assert ticket.get("employee_notified_at")
    recipients = {m["to"] for m in capture_mail}
    assert "employee@ampcus.com" in recipients
    assert "admin@ampcus.com" in recipients


def test_assign_does_not_email_solution_resolve_does(
    client, admin_headers, employee_headers, capture_mail
):
    data = _query_breach(client, employee_headers)
    assert data.get("escalated") is True
    confirmed = confirm_pending_ticket(client, employee_headers, data)
    ticket_id = confirmed["ticket_id"]
    capture_mail.clear()

    assigned = client.patch(
        f"/tickets/{ticket_id}/assign",
        headers=admin_headers,
        json={"department": "legal", "admin_notes": "Looking into it"},
    )
    assert assigned.status_code == 200
    assert not any("Update on ticket" in m["subject"] for m in capture_mail)

    resolved = client.patch(
        f"/tickets/{ticket_id}/resolve",
        headers=admin_headers,
        json={
            "status": "resolved",
            "admin_notes": "Contact Legal via security@ampcus.com immediately.",
        },
    )
    assert resolved.status_code == 200
    assert any(
        m["to"] == "employee@ampcus.com" and "Update on ticket" in m["subject"]
        for m in capture_mail
    )
    ticket = get_ticket(ticket_id)
    assert ticket["employee_resolved_notified_at"]
    assert ticket["status"] == "resolved"


def test_reminder_helper_after_two_hours(client, employee_headers, capture_mail, monkeypatch):
    data = _query_breach(client, employee_headers)
    confirmed = confirm_pending_ticket(client, employee_headers, data)
    ticket_id = confirmed["ticket_id"]
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    from app.tickets import store as store_mod

    with store_mod._lock:
        tickets = store_mod._read_all()
        for t in tickets:
            if t["id"] == ticket_id:
                t["created_at"] = old
                t["reminder_sent_at"] = None
        store_mod._write_all(tickets)

    capture_mail.clear()
    from app.tickets.notify import process_escalation_reminders

    n = process_escalation_reminders(now=datetime.now(timezone.utc), hours=2)
    assert n == 1
    assert get_ticket(ticket_id)["reminder_sent_at"]
    assert any("Reminder" in m["subject"] for m in capture_mail)
    capture_mail.clear()
    assert process_escalation_reminders(now=datetime.now(timezone.utc), hours=2) == 0
    assert capture_mail == []
