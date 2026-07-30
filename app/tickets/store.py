"""Persistent HITL ticket store — unknown routing + severity escalations."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()

TICKET_TYPE_UNKNOWN = "unknown"
TICKET_TYPE_ESCALATION = "escalation"


def _tickets_path() -> Path:
    settings = get_settings()
    base = Path(settings.chroma_persist_dir).resolve().parent
    path = base / "tickets.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_all() -> List[Dict[str, Any]]:
    path = _tickets_path()
    if not path.exists():
        return []
    try:
        tickets = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Corrupt tickets file — starting empty")
        return []
    # Backfill older tickets
    for t in tickets:
        t.setdefault("ticket_type", TICKET_TYPE_UNKNOWN)
        t.setdefault("severity", "routine")
        t.setdefault("created_by_user_id", None)
        t.setdefault("created_by_email", None)
        t.setdefault("updated_by_user_id", None)
        t.setdefault("updated_by_email", None)
    return tickets


def _write_all(tickets: List[Dict[str, Any]]) -> None:
    path = _tickets_path()
    path.write_text(json.dumps(tickets, indent=2), encoding="utf-8")


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
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "assigned_department": department if department != "unknown" else None,
        "kb_doc_id": None,
        "admin_notes": None,
        "created_by_user_id": created_by_user_id,
        "created_by_email": created_by_email,
        "updated_by_user_id": None,
        "updated_by_email": None,
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
