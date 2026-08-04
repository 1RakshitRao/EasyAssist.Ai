"""Ephemeral chat document store — one active doc per session, SQLite + dual TTL."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.audit.db import connect, init_audit_db
from app.config import get_settings
from app.documents.preview import preview_kind
from app.documents.storage import delete_session_files

logger = logging.getLogger(__name__)
_lock = threading.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _email(value: str | None) -> str:
    return (value or "").strip().lower()


def _parse_iso(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _purge_expired(conn) -> None:
    """Remove rows whose file TTL has passed; clear text when text TTL passed."""
    now = _iso(_now())
    # Null out text after text expiry (keep meta for preview)
    conn.execute(
        """
        UPDATE chat_documents
        SET text = NULL
        WHERE text IS NOT NULL
          AND COALESCE(text_expires_at, expires_at) <= ?
        """,
        (now,),
    )
    # Delete rows past file expiry
    rows = conn.execute(
        """
        SELECT session_id FROM chat_documents
        WHERE COALESCE(file_expires_at, expires_at) <= ?
        """,
        (now,),
    ).fetchall()
    for r in rows:
        delete_session_files(str(r["session_id"]))
    conn.execute(
        """
        DELETE FROM chat_documents
        WHERE COALESCE(file_expires_at, expires_at) <= ?
        """,
        (now,),
    )


def upsert_document(
    *,
    session_id: str,
    user_email: str,
    filename: str,
    text: str,
    content_type: str | None = None,
    stored_path: str | None = None,
    preview_kind_value: str | None = None,
    doc_id: str | None = None,
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
    text_ttl = int(settings.document_ttl_seconds or 7200)
    file_days = int(settings.document_file_ttl_days or 7)
    text_expires = now + timedelta(seconds=text_ttl)
    file_expires = now + timedelta(days=file_days)
    new_id = (doc_id or "").strip() or str(uuid.uuid4())
    fname = (filename or "document").strip() or "document"
    kind = preview_kind_value or preview_kind(fname)
    meta = {
        "doc_id": new_id,
        "session_id": sid,
        "user_email": email,
        "filename": fname,
        "content_type": content_type,
        "char_count": len(body),
        "created_at": _iso(now),
        "expires_at": _iso(text_expires),
        "text_expires_at": _iso(text_expires),
        "file_expires_at": _iso(file_expires),
        "stored_path": stored_path,
        "preview_kind": kind,
    }
    with _lock:
        with connect() as conn:
            _purge_expired(conn)
            conn.execute("DELETE FROM chat_documents WHERE session_id = ?", (sid,))
            conn.execute(
                """
                INSERT INTO chat_documents (
                    doc_id, session_id, user_email, filename, content_type,
                    char_count, text, created_at, expires_at,
                    stored_path, preview_kind, text_expires_at, file_expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    meta["stored_path"],
                    meta["preview_kind"],
                    meta["text_expires_at"],
                    meta["file_expires_at"],
                ),
            )
            conn.commit()
    logger.info(
        "chat document upserted session=%s doc=%s chars=%s path=%s",
        sid,
        new_id,
        meta["char_count"],
        stored_path,
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
                       char_count, text, created_at, expires_at,
                       stored_path, preview_kind, text_expires_at, file_expires_at
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
        "stored_path": row["stored_path"],
        "preview_kind": row["preview_kind"],
        "text_expires_at": row["text_expires_at"],
        "file_expires_at": row["file_expires_at"],
    }
    if include_text:
        text_exp = _parse_iso(row["text_expires_at"] or row["expires_at"])
        if text_exp and text_exp <= _now():
            out["text"] = None
            out["text_expired"] = True
        else:
            out["text"] = row["text"]
            out["text_expired"] = row["text"] is None
    return out


def document_owner_email(session_id: str, doc_id: str) -> Optional[str]:
    """Return owning email for a session/doc row, if any (after file-TTL purge)."""
    init_audit_db()
    sid = (session_id or "").strip()
    did = (doc_id or "").strip()
    if not sid or not did:
        return None
    with _lock:
        with connect() as conn:
            _purge_expired(conn)
            conn.commit()
            row = conn.execute(
                """
                SELECT user_email FROM chat_documents
                WHERE session_id = ? AND doc_id = ?
                """,
                (sid, did),
            ).fetchone()
    return _email(row["user_email"]) if row else None


def get_document_for_preview(
    session_id: str,
    doc_id: str,
    user_email: str,
) -> Optional[Dict[str, Any]]:
    """Return meta for preview if owned by user and file not expired."""
    init_audit_db()
    sid = (session_id or "").strip()
    did = (doc_id or "").strip()
    email = _email(user_email)
    if not sid or not did or not email:
        return None
    with _lock:
        with connect() as conn:
            _purge_expired(conn)
            conn.commit()
            row = conn.execute(
                """
                SELECT doc_id, session_id, user_email, filename, content_type,
                       stored_path, preview_kind, file_expires_at, created_at
                FROM chat_documents
                WHERE session_id = ? AND doc_id = ? AND user_email = ?
                """,
                (sid, did, email),
            ).fetchone()
    if not row:
        return None
    return {
        "doc_id": row["doc_id"],
        "session_id": row["session_id"],
        "user_email": row["user_email"],
        "filename": row["filename"],
        "content_type": row["content_type"],
        "stored_path": row["stored_path"],
        "preview_kind": row["preview_kind"],
        "file_expires_at": row["file_expires_at"],
        "created_at": row["created_at"],
    }


def clear_document(session_id: str, user_email: str) -> bool:
    init_audit_db()
    sid = (session_id or "").strip()
    email = _email(user_email)
    with _lock:
        with connect() as conn:
            owned = conn.execute(
                """
                SELECT session_id FROM chat_documents
                WHERE session_id = ? AND user_email = ?
                """,
                (sid, email),
            ).fetchone()
            if not owned:
                return False
            delete_session_files(sid)
            cur = conn.execute(
                "DELETE FROM chat_documents WHERE session_id = ? AND user_email = ?",
                (sid, email),
            )
            conn.commit()
            return cur.rowcount > 0
