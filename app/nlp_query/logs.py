"""Persist NLP question / SQL / answer for admin review."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.audit.db import connect, init_audit_db

logger = logging.getLogger(__name__)
_lock = threading.Lock()


def append_nlp_log(
    *,
    user: Dict[str, Any],
    question: str,
    sql_text: str | None,
    answer: str,
    allowed: bool,
    block_kind: str | None = None,
    row_count: int | None = None,
    session_id: str | None = None,
) -> Dict[str, Any]:
    init_audit_db()
    row = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user.get("id"),
        "user_email": user.get("email"),
        "user_role": user.get("role"),
        "question": question or "",
        "sql_text": sql_text or None,
        "answer": answer or "",
        "allowed": 1 if allowed else 0,
        "block_kind": block_kind,
        "row_count": row_count,
        "session_id": session_id,
    }
    with _lock:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO nlp_query_logs (
                    id, timestamp, user_id, user_email, user_role,
                    question, sql_text, answer, allowed, block_kind,
                    row_count, session_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["timestamp"],
                    row["user_id"],
                    row["user_email"],
                    row["user_role"],
                    row["question"],
                    row["sql_text"],
                    row["answer"],
                    row["allowed"],
                    row["block_kind"],
                    row["row_count"],
                    row["session_id"],
                ),
            )
            conn.commit()
    return row


def list_nlp_logs(limit: int = 100) -> List[Dict[str, Any]]:
    init_audit_db()
    lim = min(max(int(limit or 100), 1), 500)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                id, timestamp, user_id, user_email, user_role,
                question, sql_text, answer, allowed, block_kind,
                row_count, session_id
            FROM nlp_query_logs
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (lim,),
        ).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "user_id": r["user_id"],
                "user_email": r["user_email"],
                "user_role": r["user_role"],
                "question": r["question"],
                "sql": r["sql_text"],
                "answer": r["answer"],
                "allowed": bool(r["allowed"]),
                "block_kind": r["block_kind"],
                "row_count": r["row_count"],
                "session_id": r["session_id"],
            }
        )
    return out


def get_nlp_log(log_id: str) -> Optional[Dict[str, Any]]:
    init_audit_db()
    with connect() as conn:
        r = conn.execute(
            """
            SELECT
                id, timestamp, user_id, user_email, user_role,
                question, sql_text, answer, allowed, block_kind,
                row_count, session_id
            FROM nlp_query_logs
            WHERE id = ?
            """,
            (log_id,),
        ).fetchone()
    if not r:
        return None
    return {
        "id": r["id"],
        "timestamp": r["timestamp"],
        "user_id": r["user_id"],
        "user_email": r["user_email"],
        "user_role": r["user_role"],
        "question": r["question"],
        "sql": r["sql_text"],
        "answer": r["answer"],
        "allowed": bool(r["allowed"]),
        "block_kind": r["block_kind"],
        "row_count": r["row_count"],
        "session_id": r["session_id"],
    }
