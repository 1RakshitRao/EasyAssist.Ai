"""Persistent HITL ticket store — unknown routing + severity escalations."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()

TICKET_TYPE_UNKNOWN = "unknown"
TICKET_TYPE_ESCALATION = "escalation"

_NOTIFY_DEFAULTS = {
    "admin_notified_at": None,
    "employee_notified_at": None,
    "reminder_sent_at": None,
    "employee_resolved_notified_at": None,
}


def _tickets_path() -> Path:
    settings = get_settings()
    base = Path(settings.chroma_persist_dir).resolve().parent
    path = base / "tickets.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _backfill(ticket: Dict[str, Any]) -> Dict[str, Any]:
    ticket.setdefault("ticket_type", TICKET_TYPE_UNKNOWN)
    ticket.setdefault("severity", "routine")
    ticket.setdefault("created_by_user_id", None)
    ticket.setdefault("created_by_email", None)
    ticket.setdefault("updated_by_user_id", None)
    ticket.setdefault("updated_by_email", None)
    ticket.setdefault("resolved_at", None)
    for key, default in _NOTIFY_DEFAULTS.items():
        ticket.setdefault(key, default)
    return ticket


def _read_all() -> List[Dict[str, Any]]:
    path = _tickets_path()
    if not path.exists():
        return []
    try:
        tickets = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Corrupt tickets file — starting empty")
        return []
    return [_backfill(t) for t in tickets]


def _write_all(tickets: List[Dict[str, Any]]) -> None:
    path = _tickets_path()
    path.write_text(json.dumps(tickets, indent=2), encoding="utf-8")


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def create_ticket(
    question: str,
    normalized_query: str,
    reason: str,
    *,
    ticket_type: str = TICKET_TYPE_UNKNOWN,
    department: str = "unknown",
    severity: str = "routine",
    attempted_depts: Optional[List[str]] = None,
    created_by_user_id: Optional[str] = None,
    created_by_email: Optional[str] = None,
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    ticket = {
        "id": str(uuid.uuid4()),
        "question": question,
        "normalized_query": normalized_query,
        "ticket_type": ticket_type,
        "department": department,
        "severity": severity,
        "status": "open",
        "reason": reason,
        "attempted_depts": list(attempted_depts or []),
        "created_at": now,
        "updated_at": now,
        "assigned_department": department if department != "unknown" else None,
        "kb_doc_id": None,
        "admin_notes": None,
        "created_by_user_id": created_by_user_id,
        "created_by_email": created_by_email,
        "updated_by_user_id": None,
        "updated_by_email": None,
        "resolved_at": None,
        **{k: None for k in _NOTIFY_DEFAULTS},
    }
    with _lock:
        tickets = _read_all()
        tickets.append(ticket)
        _write_all(tickets)
    logger.info(
        "Created HITL ticket id=%s type=%s dept=%s reason=%s",
        ticket["id"],
        ticket_type,
        department,
        reason,
    )
    try:
        from app.tickets.inbox import push_ticket_notification

        push_ticket_notification(ticket)
    except Exception as exc:
        logger.warning(
            "in-app ticket notification failed ticket_id=%s: %s",
            ticket["id"],
            exc,
        )
    return ticket


def list_tickets(
    status: Optional[str] = None,
    ticket_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    with _lock:
        tickets = _read_all()
    if status:
        tickets = [t for t in tickets if t.get("status") == status]
    if ticket_type:
        tickets = [t for t in tickets if t.get("ticket_type", TICKET_TYPE_UNKNOWN) == ticket_type]
    return tickets


def list_tickets_for_user(
    email: str,
    *,
    open_only: bool = True,
) -> List[Dict[str, Any]]:
    """Tickets filed by this employee (matched on created_by_email)."""
    email_norm = str(email or "").strip().lower()
    if not email_norm:
        return []
    with _lock:
        tickets = _read_all()
    mine = [
        t
        for t in tickets
        if str(t.get("created_by_email") or "").strip().lower() == email_norm
    ]
    if open_only:
        mine = [t for t in mine if t.get("status") in {"open", "assigned"}]
    return sorted(
        mine,
        key=lambda t: str(t.get("created_at") or ""),
        reverse=True,
    )


def list_due_escalation_reminders(
    *,
    now: Optional[datetime] = None,
    hours: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Escalation tickets still not resolved, older than `hours`, with no reminder yet.
    Assigned counts as not worked on for reminder purposes.
    """
    settings = get_settings()
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    threshold_hours = float(
        hours if hours is not None else settings.escalation_reminder_hours
    )
    cutoff = clock - timedelta(hours=threshold_hours)

    due: List[Dict[str, Any]] = []
    for ticket in list_tickets(ticket_type=TICKET_TYPE_ESCALATION):
        if ticket.get("status") == "resolved":
            continue
        if ticket.get("reminder_sent_at"):
            continue
        created = _parse_ts(ticket.get("created_at"))
        if not created:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created <= cutoff:
            due.append(ticket)
    return due


def count_open(ticket_type: Optional[str] = None) -> int:
    return len(list_tickets(status="open", ticket_type=ticket_type))


def get_ticket(ticket_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        for t in _read_all():
            if t.get("id") == ticket_id:
                return t
    return None


def update_ticket(ticket_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    with _lock:
        tickets = _read_all()
        for i, t in enumerate(tickets):
            if t.get("id") != ticket_id:
                continue
            t.update({k: v for k, v in fields.items() if v is not None})
            t["updated_at"] = datetime.now(timezone.utc).isoformat()
            tickets[i] = t
            _write_all(tickets)
            return t
    return None
