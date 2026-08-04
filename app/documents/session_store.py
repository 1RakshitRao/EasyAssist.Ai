"""Ephemeral chat document store — one active doc per session, SQLite + TTL."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.audit.db import connect, init_audit_db
from app.config import get_settings

logger = logging.getLogger(__name__)
_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _email(value: str | None) -> str:
    return (value or "").strip().lower()


def _purge_expired(conn) -> None:
    now = _iso(_now())
    conn.execute("DELETE FROM chat_documents WHERE expires_at <= ?", (now,))


def upsert_document(
    *,
    session_id: str,
    user_email: str,
    filename: str,
    text: str,
    content_type: str | None = None,
) -> Dict[str, Any]:
    """Replace any existing doc for this session with a new one."""
    init_audit_db()
    sid = (session_id or "").strip()
    email = _email(user_email)
    if not sid:
        raise ValueError("session_id required")
    if not email:
        raise ValueError("user_email required")
    body = text or ""
    if not body.strip():
        raise ValueError("document text is empty")

    settings = get_settings()
    now = _now()
    expires = now + timedelta(seconds=int(settings.document_ttl_seconds or 7200))
    doc_id = str(uuid.uuid4())
    meta = {
        "doc_id": doc_id,
        "session_id": sid,
        "user_email": email,
        "filename": (filename or "document").strip() or "document",
        "content_type": content_type,
        "char_count": len(body),
        "created_at": _iso(now),
        "expires_at": _iso(expires),
    }
    with _lock:
        with connect() as conn:
            _purge_expired(conn)
            conn.execute("DELETE FROM chat_documents WHERE session_id = ?", (sid,))
            conn.execute(
                """
                INSERT INTO chat_documents (
                    doc_id, session_id, user_email, filename, content_type,
                    char_count, text, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    meta["doc_id"],
                    meta["session_id"],
                    meta["user_email"],
                    meta["filename"],
                    meta["content_type"],
                    meta["char_count"],
                    body,
                    meta["created_at"],
                    meta["expires_at"],
                ),
            )
            conn.commit()
    logger.info(
        "chat document upserted session=%s doc=%s chars=%s",
        sid,
        doc_id,
        meta["char_count"],
    )
    return meta


def get_active_document(
    session_id: str,
    user_email: str,
    *,
    include_text: bool = True,
) -> Optional[Dict[str, Any]]:
    init_audit_db()
    sid = (session_id or "").strip()
    email = _email(user_email)
    if not sid or not email:
        return None
    with _lock:
        with connect() as conn:
            _purge_expired(conn)
            conn.commit()
            row = conn.execute(
                """
                SELECT doc_id, session_id, user_email, filename, content_type,
                       char_count, text, created_at, expires_at
                FROM chat_documents
                WHERE session_id = ? AND user_email = ?
                """,
                (sid, email),
            ).fetchone()
    if not row:
        return None
    out: Dict[str, Any] = {
        "doc_id": row["doc_id"],
        "session_id": row["session_id"],
        "user_email": row["user_email"],
        "filename": row["filename"],
        "content_type": row["content_type"],
        "char_count": row["char_count"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
    }
    if include_text:
        out["text"] = row["text"]
    return out


def clear_document(session_id: str, user_email: str) -> bool:
    init_audit_db()
    sid = (session_id or "").strip()
    email = _email(user_email)
    with _lock:
        with connect() as conn:
            cur = conn.execute(
                "DELETE FROM chat_documents WHERE session_id = ? AND user_email = ?",
                (sid, email),
            )
            conn.commit()
            return cur.rowcount > 0
