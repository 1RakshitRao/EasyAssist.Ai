"""In-app admin/agent notifications for new HITL tickets."""

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
_MAX_ITEMS = 200


def _inbox_path() -> Path:
    settings = get_settings()
    base = Path(settings.chroma_persist_dir).resolve().parent
    path = base / "notifications.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_all() -> List[Dict[str, Any]]:
    path = _inbox_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Corrupt notifications file — starting empty")
        return []
    return data if isinstance(data, list) else []


def _write_all(items: List[Dict[str, Any]]) -> None:
    path = _inbox_path()
    path.write_text(json.dumps(items, indent=2), encoding="utf-8")


def push_ticket_notification(ticket: Dict[str, Any]) -> Dict[str, Any]:
    """Record an in-app alert when a ticket is created."""
    ticket_type = str(ticket.get("ticket_type") or "unknown").lower()
    severity = str(ticket.get("severity") or "routine").lower()
    question = str(ticket.get("question") or "").strip()
    preview = question if len(question) <= 120 else question[:117] + "..."
    kind_label = "Escalation" if ticket_type == "escalation" else "Unknown ticket"
    title = f"New {kind_label.lower()}"
    if severity == "high":
        title = f"High-severity {kind_label.lower()}"

    note = {
        "id": str(uuid.uuid4()),
        "kind": "ticket_created",
        "title": title,
        "body": preview or "A new helpdesk ticket needs review.",
        "ticket_id": ticket.get("id"),
        "ticket_type": ticket_type,
        "severity": severity,
        "department": ticket.get("department"),
        "created_by_email": ticket.get("created_by_email"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "read_at": None,
    }
    with _lock:
        items = _read_all()
        items.insert(0, note)
        _write_all(items[:_MAX_ITEMS])
    logger.info(
        "in-app notification created id=%s ticket_id=%s",
        note["id"],
        note.get("ticket_id"),
    )
    return note


def list_notifications(
    *, unread_only: bool = False, limit: int = 50
) -> List[Dict[str, Any]]:
    with _lock:
        items = _read_all()
    if unread_only:
        items = [n for n in items if not n.get("read_at")]
    return items[: max(1, min(limit, _MAX_ITEMS))]


def unread_count() -> int:
    with _lock:
        items = _read_all()
    return sum(1 for n in items if not n.get("read_at"))


def mark_read(notification_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        items = _read_all()
        for note in items:
            if note.get("id") == notification_id:
                if not note.get("read_at"):
                    note["read_at"] = datetime.now(timezone.utc).isoformat()
                    _write_all(items)
                return note
    return None


def mark_all_read() -> int:
    now = datetime.now(timezone.utc).isoformat()
    changed = 0
    with _lock:
        items = _read_all()
        for note in items:
            if not note.get("read_at"):
                note["read_at"] = now
                changed += 1
        if changed:
            _write_all(items)
    return changed
