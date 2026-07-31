"""Ticket email notifications — open, 2h reminder, resolved."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.audit.emailer import send_email
from app.auth.users import list_users
from app.config import get_settings
from app.tickets.store import (
    TICKET_TYPE_ESCALATION,
    get_ticket,
    list_due_escalation_reminders,
    update_ticket,
)

logger = logging.getLogger(__name__)


def app_base_url() -> str:
    settings = get_settings()
    base = (settings.app_base_url or settings.training_base_url or "").strip()
    return base.rstrip("/") or "http://127.0.0.1:8080"


def admin_recipient_emails() -> List[str]:
    emails: List[str] = []
    for user in list_users():
        if not user.get("active", True):
            continue
        if str(user.get("role") or "").lower() != "admin":
            continue
        email = str(user.get("email") or "").strip().lower()
        if email:
            emails.append(email)
    if emails:
        return sorted(set(emails))
    fallback = (get_settings().admin_email or "").strip().lower()
    return [fallback] if fallback else []


def _ticket_summary(ticket: Dict[str, Any]) -> str:
    return "\n".join(
        [
            f"Ticket ID: {ticket.get('id')}",
            f"Type: {ticket.get('ticket_type')}",
            f"Status: {ticket.get('status')}",
            f"Department: {ticket.get('department')}",
            f"Severity: {ticket.get('severity')}",
            f"Employee: {ticket.get('created_by_email') or 'unknown'}",
            f"Created: {ticket.get('created_at')}",
            f"Reason: {ticket.get('reason') or '—'}",
            "",
            "Question:",
            str(ticket.get("question") or ""),
        ]
    )


def build_opened_admin_email(ticket: Dict[str, Any]) -> tuple[str, str]:
    link = f"{app_base_url()}/"
    body = "\n".join(
        [
            "A high-severity / escalation helpdesk ticket needs review.",
            "",
            _ticket_summary(ticket),
            "",
            f"Open Ampcus Helpdesk: {link}",
            "Escalations are under the Escalations sidebar view.",
            "",
            "— Ampcus Helpdesk",
        ]
    )
    return (
        f"[Ampcus] High-severity ticket {ticket.get('id')}",
        body,
    )


def build_opened_employee_email(ticket: Dict[str, Any]) -> tuple[str, str]:
    hours = int(get_settings().escalation_reminder_hours)
    body = "\n".join(
        [
            "Hello,",
            "",
            "Your Ampcus Helpdesk request was flagged as high severity and escalated "
            "for human review.",
            "",
            f"Ticket ID: {ticket.get('id')}",
            f"Department: {ticket.get('department')}",
            "",
            "Question:",
            str(ticket.get("question") or ""),
            "",
            f"You should hear back within about {hours} hours.",
            "",
            "— Ampcus Helpdesk",
        ]
    )
    return (
        f"[Ampcus] Your request was escalated ({ticket.get('id')})",
        body,
    )


def build_reminder_admin_email(ticket: Dict[str, Any]) -> tuple[str, str]:
    hours = int(get_settings().escalation_reminder_hours)
    link = f"{app_base_url()}/"
    body = "\n".join(
        [
            f"Reminder: escalation ticket is still unresolved after {hours} hours.",
            "",
            _ticket_summary(ticket),
            "",
            f"Open Ampcus Helpdesk: {link}",
            "",
            "— Ampcus Helpdesk",
        ]
    )
    return (
        f"[Ampcus] Reminder — unresolved ticket {ticket.get('id')}",
        body,
    )


def build_resolved_employee_email(
    ticket: Dict[str, Any], *, solution: str
) -> tuple[str, str]:
    body = "\n".join(
        [
            "Hello,",
            "",
            "An update is available for your escalated Ampcus Helpdesk request.",
            "",
            f"Ticket ID: {ticket.get('id')}",
            f"Department: {ticket.get('department')}",
            f"Status: {ticket.get('status')}",
            "",
            "Your question:",
            str(ticket.get("question") or ""),
            "",
            "Solution / notes from the helpdesk team:",
            solution.strip() or "(no notes provided)",
            "",
            "— Ampcus Helpdesk",
        ]
    )
    return (
        f"[Ampcus] Update on ticket {ticket.get('id')}",
        body,
    )


def notify_ticket_opened(ticket: Dict[str, Any]) -> Dict[str, Any]:
    """Email admins + employee when a high/escalation (or high unknown) ticket opens."""
    now = datetime.now(timezone.utc).isoformat()
    updates: Dict[str, Any] = {}

    if not ticket.get("admin_notified_at"):
        subject, body = build_opened_admin_email(ticket)
        for email in admin_recipient_emails():
            try:
                send_email(to=email, subject=subject, body=body)
            except Exception as exc:
                logger.warning("Admin open notify failed to=%s: %s", email, exc)
        updates["admin_notified_at"] = now

    employee = str(ticket.get("created_by_email") or "").strip().lower()
    if employee and not ticket.get("employee_notified_at"):
        subject, body = build_opened_employee_email(ticket)
        try:
            send_email(to=employee, subject=subject, body=body)
        except Exception as exc:
            logger.warning("Employee open notify failed to=%s: %s", employee, exc)
        updates["employee_notified_at"] = now

    if updates:
        updated = update_ticket(ticket["id"], **updates)
        return updated or {**ticket, **updates}
    return ticket


def notify_ticket_resolved(
    ticket: Dict[str, Any], *, solution: Optional[str] = None
) -> Dict[str, Any]:
    """Email employee once when a solution is recorded (resolve or promote)."""
    if ticket.get("status") != "resolved":
        return ticket
    if ticket.get("employee_resolved_notified_at"):
        return ticket
    employee = str(ticket.get("created_by_email") or "").strip().lower()
    if not employee:
        return ticket

    text = (solution or ticket.get("admin_notes") or "").strip()
    if not text:
        return ticket

    subject, body = build_resolved_employee_email(ticket, solution=text)
    try:
        send_email(to=employee, subject=subject, body=body)
    except Exception as exc:
        logger.warning("Employee resolved notify failed to=%s: %s", employee, exc)

    now = datetime.now(timezone.utc).isoformat()
    updated = update_ticket(ticket["id"], employee_resolved_notified_at=now)
    return updated or {**ticket, "employee_resolved_notified_at": now}


def process_escalation_reminders(
    *, now: Optional[datetime] = None, hours: Optional[float] = None
) -> int:
    """Send one admin reminder per due escalation ticket. Returns count reminded."""
    due = list_due_escalation_reminders(now=now, hours=hours)
    sent = 0
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    for ticket in due:
        # Re-check freshness
        fresh = get_ticket(str(ticket.get("id") or ""))
        if not fresh or fresh.get("status") == "resolved" or fresh.get("reminder_sent_at"):
            continue
        subject, body = build_reminder_admin_email(fresh)
        for email in admin_recipient_emails():
            try:
                send_email(to=email, subject=subject, body=body)
            except Exception as exc:
                logger.warning("Admin reminder failed to=%s: %s", email, exc)
        update_ticket(fresh["id"], reminder_sent_at=stamp)
        sent += 1
        logger.info("Escalation reminder sent ticket_id=%s", fresh["id"])
    return sent
