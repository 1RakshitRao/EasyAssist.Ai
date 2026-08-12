"""Pending multi-turn infrastructure action state on chat sessions."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, Optional

from app.audit.db import connect, init_audit_db

logger = logging.getLogger(__name__)
_lock = threading.Lock()


def save_pending(session_id: str, payload: Dict[str, Any]) -> None:
    init_audit_db()
    sid = (session_id or "").strip()
    if not sid:
        return
    blob = json.dumps(payload)
    with _lock:
        with connect() as conn:
            conn.execute(
                "UPDATE chat_sessions SET pending_infrastructure_json = ? WHERE session_id = ?",
                (blob, sid),
            )
            conn.commit()


def get_pending(session_id: str) -> Optional[Dict[str, Any]]:
    init_audit_db()
    sid = (session_id or "").strip()
    if not sid:
        return None
    with _lock:
        with connect() as conn:
            row = conn.execute(
                "SELECT pending_infrastructure_json FROM chat_sessions WHERE session_id = ?",
                (sid,),
            ).fetchone()
    if not row or not row["pending_infrastructure_json"]:
        return None
    try:
        data = json.loads(row["pending_infrastructure_json"])
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def clear_pending(session_id: str) -> None:
    init_audit_db()
    sid = (session_id or "").strip()
    if not sid:
        return
    with _lock:
        with connect() as conn:
            conn.execute(
                "UPDATE chat_sessions SET pending_infrastructure_json = NULL WHERE session_id = ?",
                (sid,),
            )
            conn.commit()
