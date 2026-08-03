"""SQLite chat session + message store (no Redis hot cache)."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.audit.db import connect, init_audit_db

logger = logging.getLogger(__name__)
_lock = threading.Lock()

CHAT_CONTEXT_LIMIT = 6
TITLE_MAX_LEN = 50


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _email(value: str | None) -> str:
    return (value or "").strip().lower()


def trim_title(text: str, max_len: int = TITLE_MAX_LEN) -> str:
    cleaned = " ".join((text or "").strip().split())
    if len(cleaned) <= max_len:
        return cleaned or "New chat"
    return cleaned[: max_len - 1].rstrip() + "…"


def new_session_id() -> str:
    return f"sess_{uuid.uuid4().hex}"


def ensure_session(
    session_id: str | None,
    user_email: str,
    title_seed: str = "",
) -> str:
    """Create session if missing; return session_id (generated when absent)."""
    init_audit_db()
    email = _email(user_email)
    sid = (session_id or "").strip() or new_session_id()
    now = _now()
    title = trim_title(title_seed) if title_seed else "New chat"
    with _lock:
        with connect() as conn:
            row = conn.execute(
                "SELECT session_id FROM chat_sessions WHERE session_id = ?",
                (sid,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO chat_sessions (
                        session_id, user_email, title, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (sid, email, title, now, now),
                )
                conn.commit()
                logger.info("chat session created id=%s email=%s", sid, email)
            else:
                owned = conn.execute(
                    """
                    SELECT session_id FROM chat_sessions
                    WHERE session_id = ? AND user_email = ?
                    """,
                    (sid, email),
                ).fetchone()
                if owned is None:
                    raise PermissionError("session belongs to another user")
    return sid


def save_message(
    *,
    session_id: str,
    user_email: str,
    role: str,
    content: str,
    department: str | None = None,
    cost_usd: float | None = None,
) -> Dict[str, Any]:
    init_audit_db()
    email = _email(user_email)
    sid = (session_id or "").strip()
    if not sid:
        raise ValueError("session_id required")
    role_n = (role or "").strip().lower()
    if role_n not in {"user", "assistant"}:
        raise ValueError("role must be user or assistant")
    now = _now()
    msg_id = str(uuid.uuid4())
    with _lock:
        with connect() as conn:
            owned = conn.execute(
                """
                SELECT session_id, title FROM chat_sessions
                WHERE session_id = ? AND user_email = ?
                """,
                (sid, email),
            ).fetchone()
            if owned is None:
                raise PermissionError("session not found or not owned")
            # Set title from first user message when still placeholder
            if role_n == "user" and (owned["title"] or "") in {"", "New chat"}:
                conn.execute(
                    "UPDATE chat_sessions SET title = ?, updated_at = ? WHERE session_id = ?",
                    (trim_title(content), now, sid),
                )
            else:
                conn.execute(
                    "UPDATE chat_sessions SET updated_at = ? WHERE session_id = ?",
                    (now, sid),
                )
            conn.execute(
                """
                INSERT INTO chat_messages (
                    id, session_id, user_email, role, content,
                    created_at, department, cost_usd
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg_id,
                    sid,
                    email,
                    role_n,
                    content or "",
                    now,
                    department,
                    float(cost_usd) if cost_usd is not None else None,
                ),
            )
            conn.commit()
    return {
        "id": msg_id,
        "session_id": sid,
        "user_email": email,
        "role": role_n,
        "content": content or "",
        "created_at": now,
        "department": department,
        "cost_usd": cost_usd,
    }


def load_history(
    session_id: str,
    user_email: str,
    limit: int = CHAT_CONTEXT_LIMIT,
) -> List[Dict[str, str]]:
    """Last N messages for LLM context, oldest first. Empty if session missing."""
    init_audit_db()
    email = _email(user_email)
    sid = (session_id or "").strip()
    if not sid:
        return []
    with connect() as conn:
        owned = conn.execute(
            """
            SELECT session_id FROM chat_sessions
            WHERE session_id = ? AND user_email = ?
            """,
            (sid, email),
        ).fetchone()
        if owned is None:
            return []
        rows = conn.execute(
            """
            SELECT role, content FROM chat_messages
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (sid, int(limit)),
        ).fetchall()
    # rows are newest-first; reverse for chronological LLM order
    out = [{"role": r["role"], "content": r["content"] or ""} for r in reversed(rows)]
    return out


def message_count(session_id: str, user_email: str) -> int:
    init_audit_db()
    email = _email(user_email)
    sid = (session_id or "").strip()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM chat_messages m
            JOIN chat_sessions s ON s.session_id = m.session_id
            WHERE m.session_id = ? AND s.user_email = ?
            """,
            (sid, email),
        ).fetchone()
    return int(row["n"] or 0) if row else 0


def list_sessions(user_email: str) -> List[Dict[str, Any]]:
    init_audit_db()
    email = _email(user_email)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                s.session_id AS session_id,
                s.title AS title,
                s.created_at AS created_at,
                s.updated_at AS last_message_at,
                (
                    SELECT COUNT(*) FROM chat_messages m
                    WHERE m.session_id = s.session_id
                ) AS message_count
            FROM chat_sessions s
            WHERE s.user_email = ?
            ORDER BY s.updated_at DESC
            """,
            (email,),
        ).fetchall()
    return [
        {
            "session_id": r["session_id"],
            "title": r["title"],
            "created_at": r["created_at"],
            "last_message_at": r["last_message_at"],
            "message_count": int(r["message_count"] or 0),
        }
        for r in rows
    ]


def get_session(session_id: str, user_email: str) -> Optional[Dict[str, Any]]:
    init_audit_db()
    email = _email(user_email)
    sid = (session_id or "").strip()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT session_id, user_email, title, created_at, updated_at
            FROM chat_sessions
            WHERE session_id = ? AND user_email = ?
            """,
            (sid, email),
        ).fetchone()
    return dict(row) if row else None


def get_messages(session_id: str, user_email: str) -> Optional[List[Dict[str, Any]]]:
    """Full history oldest-first, or None if session missing/not owned."""
    init_audit_db()
    email = _email(user_email)
    sid = (session_id or "").strip()
    with connect() as conn:
        owned = conn.execute(
            """
            SELECT session_id FROM chat_sessions
            WHERE session_id = ? AND user_email = ?
            """,
            (sid, email),
        ).fetchone()
        if owned is None:
            return None
        rows = conn.execute(
            """
            SELECT id, role, content, created_at, department, cost_usd
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (sid,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "role": r["role"],
            "content": r["content"] or "",
            "created_at": r["created_at"],
            "department": r["department"],
            "cost_usd": r["cost_usd"],
        }
        for r in rows
    ]


def rename_session(session_id: str, user_email: str, title: str) -> Optional[Dict[str, Any]]:
    """Update session title. Returns updated row or None if missing/not owned."""
    init_audit_db()
    email = _email(user_email)
    sid = (session_id or "").strip()
    new_title = trim_title(title)
    now = _now()
    with _lock:
        with connect() as conn:
            owned = conn.execute(
                """
                SELECT session_id FROM chat_sessions
                WHERE session_id = ? AND user_email = ?
                """,
                (sid, email),
            ).fetchone()
            if owned is None:
                return None
            conn.execute(
                """
                UPDATE chat_sessions
                SET title = ?, updated_at = ?
                WHERE session_id = ? AND user_email = ?
                """,
                (new_title, now, sid, email),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT session_id, user_email, title, created_at, updated_at
                FROM chat_sessions
                WHERE session_id = ? AND user_email = ?
                """,
                (sid, email),
            ).fetchone()
    return dict(row) if row else None


def delete_session(session_id: str, user_email: str) -> bool:
    """Delete session + messages. Returns False if not found/not owned."""
    init_audit_db()
    email = _email(user_email)
    sid = (session_id or "").strip()
    with _lock:
        with connect() as conn:
            owned = conn.execute(
                """
                SELECT session_id FROM chat_sessions
                WHERE session_id = ? AND user_email = ?
                """,
                (sid, email),
            ).fetchone()
            if owned is None:
                return False
            conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (sid,))
            conn.execute("DELETE FROM chat_sessions WHERE session_id = ?", (sid,))
            conn.commit()
    logger.info("chat session deleted id=%s email=%s", sid, email)
    return True
