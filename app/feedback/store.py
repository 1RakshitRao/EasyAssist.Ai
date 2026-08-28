"""SQLite persistence for answer like/dislike feedback."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.audit.db import connect, init_audit_db
from app.rag.chroma_store import DEPARTMENTS, NearDuplicateError, get_store

logger = logging.getLogger(__name__)

_lock = __import__("threading").Lock()

VALID_RATINGS = frozenset({"up", "down"})
VALID_STATUSES = frozenset({"open", "applied", "dismissed"})


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _email(value: str) -> str:
    return (value or "").strip().lower()


def _row_to_dict(row: Any) -> Dict[str, Any]:
    sources: List[str] = []
    raw = row["sources_json"]
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                sources = [str(x) for x in parsed]
        except (TypeError, json.JSONDecodeError):
            sources = []
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "user_email": row["user_email"],
        "session_id": row["session_id"],
        "message_id": row["message_id"],
        "question": row["question"] or "",
        "answer": row["answer"] or "",
        "rating": row["rating"],
        "comment": row["comment"],
        "corrected_answer": row["corrected_answer"],
        "department": row["department"],
        "sources": sources,
        "status": row["status"],
        "kb_doc_id": row["kb_doc_id"],
        "applied_by": row["applied_by"],
        "applied_at": row["applied_at"],
    }


def create_feedback(
    *,
    user_email: str,
    message_id: str,
    question: str,
    answer: str,
    rating: str,
    session_id: str | None = None,
    comment: str | None = None,
    corrected_answer: str | None = None,
    department: str | None = None,
    sources: list[str] | None = None,
) -> Dict[str, Any]:
    """Insert or replace feedback for (message_id, user)."""
    init_audit_db()
    email = _email(user_email)
    mid = (message_id or "").strip()
    rate = (rating or "").strip().lower()
    if not email:
        raise ValueError("user_email required")
    if not mid:
        raise ValueError("message_id required")
    if rate not in VALID_RATINGS:
        raise ValueError("rating must be 'up' or 'down'")
    q = (question or "").strip()
    a = (answer or "").strip()
    if not q or not a:
        raise ValueError("question and answer required")

    comment_n = (comment or "").strip() or None
    corrected_n = (corrected_answer or "").strip() or None
    if rate == "up":
        comment_n = None
        corrected_n = None

    dept = (department or "").strip().lower() or None
    sources_json = json.dumps(list(sources or []), ensure_ascii=False)
    now = _now()
    fid = str(uuid.uuid4())

    with _lock:
        with connect() as conn:
            existing = conn.execute(
                """
                SELECT id FROM answer_feedback
                WHERE message_id = ? AND user_email = ?
                """,
                (mid, email),
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE answer_feedback SET
                        created_at = ?,
                        session_id = ?,
                        question = ?,
                        answer = ?,
                        rating = ?,
                        comment = ?,
                        corrected_answer = ?,
                        department = ?,
                        sources_json = ?,
                        status = 'open',
                        kb_doc_id = NULL,
                        applied_by = NULL,
                        applied_at = NULL
                    WHERE id = ?
                    """,
                    (
                        now,
                        (session_id or "").strip() or None,
                        q,
                        a,
                        rate,
                        comment_n,
                        corrected_n,
                        dept,
                        sources_json,
                        existing["id"],
                    ),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM answer_feedback WHERE id = ?",
                    (existing["id"],),
                ).fetchone()
                return _row_to_dict(row)

            conn.execute(
                """
                INSERT INTO answer_feedback (
                    id, created_at, user_email, session_id, message_id,
                    question, answer, rating, comment, corrected_answer,
                    department, sources_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
                """,
                (
                    fid,
                    now,
                    email,
                    (session_id or "").strip() or None,
                    mid,
                    q,
                    a,
                    rate,
                    comment_n,
                    corrected_n,
                    dept,
                    sources_json,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM answer_feedback WHERE id = ?", (fid,)
            ).fetchone()
            return _row_to_dict(row)


def get_feedback_for_message(
    message_id: str, user_email: str
) -> Optional[Dict[str, Any]]:
    init_audit_db()
    mid = (message_id or "").strip()
    email = _email(user_email)
    if not mid or not email:
        return None
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM answer_feedback
            WHERE message_id = ? AND user_email = ?
            """,
            (mid, email),
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_feedback_for_session(
    session_id: str, user_email: str
) -> List[Dict[str, Any]]:
    init_audit_db()
    sid = (session_id or "").strip()
    email = _email(user_email)
    if not sid or not email:
        return []
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM answer_feedback
            WHERE session_id = ? AND user_email = ?
            ORDER BY created_at ASC
            """,
            (sid, email),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_feedback(
    *,
    status: str | None = None,
    rating: str | None = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    init_audit_db()
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        st = status.strip().lower()
        if st not in VALID_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(VALID_STATUSES))}")
        clauses.append("status = ?")
        params.append(st)
    if rating:
        rt = rating.strip().lower()
        if rt not in VALID_RATINGS:
            raise ValueError("rating must be 'up' or 'down'")
        clauses.append("rating = ?")
        params.append(rt)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    lim = max(1, min(int(limit or 100), 500))
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM answer_feedback
            {where}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (*params, lim),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_feedback(feedback_id: str) -> Optional[Dict[str, Any]]:
    init_audit_db()
    fid = (feedback_id or "").strip()
    if not fid:
        return None
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM answer_feedback WHERE id = ?", (fid,)
        ).fetchone()
    return _row_to_dict(row) if row else None


def dismiss_feedback(feedback_id: str, *, by_email: str) -> Optional[Dict[str, Any]]:
    init_audit_db()
    fid = (feedback_id or "").strip()
    if not fid:
        return None
    now = _now()
    with _lock:
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM answer_feedback WHERE id = ?", (fid,)
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE answer_feedback
                SET status = 'dismissed', applied_by = ?, applied_at = ?
                WHERE id = ?
                """,
                (_email(by_email), now, fid),
            )
            conn.commit()
            updated = conn.execute(
                "SELECT * FROM answer_feedback WHERE id = ?", (fid,)
            ).fetchone()
    return _row_to_dict(updated)


def apply_feedback_to_kb(
    feedback_id: str,
    *,
    by_email: str,
    department: str | None = None,
    answer_override: str | None = None,
    title: str | None = None,
) -> Dict[str, Any]:
    """
    Promote feedback Q&A into Chroma.
    Returns {feedback, kb_doc_id, duplicate_of?, duplicate_title?}.
    Raises ValueError / NearDuplicateError / KeyError.
    """
    init_audit_db()
    item = get_feedback(feedback_id)
    if not item:
        raise KeyError("feedback not found")
    if item["status"] == "applied" and item.get("kb_doc_id"):
        raise ValueError("feedback already applied to KB")

    dept = (
        (department or item.get("department") or "")
        .strip()
        .lower()
    )
    if dept not in DEPARTMENTS:
        raise ValueError(
            f"department must be one of: {', '.join(DEPARTMENTS)}"
        )

    answer_text = (
        (answer_override or "").strip()
        or (item.get("corrected_answer") or "").strip()
        or (item.get("answer") or "").strip()
    )
    if not answer_text:
        raise ValueError("no answer text to promote")

    question = (item.get("question") or "").strip()
    doc_title = (title or "").strip() or f"FAQ: {question[:80]}"
    body = f"Question: {question}\n\nAnswer: {answer_text}"

    store = get_store()
    ids = store.add_documents(
        dept,
        [
            {
                "title": doc_title,
                "content": body,
                "metadata": {
                    "source": "answer_feedback",
                    "feedback_id": feedback_id,
                    "rating": item.get("rating") or "",
                },
            }
        ],
        check_duplicates=True,
    )
    kb_doc_id = ids[0]
    now = _now()
    with _lock:
        with connect() as conn:
            conn.execute(
                """
                UPDATE answer_feedback
                SET status = 'applied',
                    department = ?,
                    kb_doc_id = ?,
                    applied_by = ?,
                    applied_at = ?,
                    corrected_answer = COALESCE(?, corrected_answer)
                WHERE id = ?
                """,
                (
                    dept,
                    kb_doc_id,
                    _email(by_email),
                    now,
                    (answer_override or "").strip() or None,
                    feedback_id,
                ),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM answer_feedback WHERE id = ?", (feedback_id,)
            ).fetchone()
    return {"feedback": _row_to_dict(row), "kb_doc_id": kb_doc_id}


def export_preference_pairs(
    *,
    rating: str | None = None,
    limit: int = 5000,
) -> List[Dict[str, Any]]:
    """Build DPO-style preference rows for offline fine-tuning."""
    init_audit_db()
    lim = max(1, min(int(limit or 5000), 20000))
    clauses: list[str] = []
    params: list[Any] = []
    if rating:
        rt = rating.strip().lower()
        if rt not in VALID_RATINGS:
            raise ValueError("rating must be 'up' or 'down'")
        clauses.append("rating = ?")
        params.append(rt)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM answer_feedback
            {where}
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (*params, lim),
        ).fetchall()

    out: List[Dict[str, Any]] = []
    for row in rows:
        item = _row_to_dict(row)
        rate = item["rating"]
        if rate == "down":
            out.append(
                {
                    "prompt": item["question"],
                    "rejected": item["answer"],
                    "chosen": (item.get("corrected_answer") or "").strip(),
                    "rating": "down",
                    "department": item.get("department") or "",
                    "feedback_id": item["id"],
                    "comment": item.get("comment") or "",
                }
            )
        else:
            out.append(
                {
                    "prompt": item["question"],
                    "rejected": "",
                    "chosen": item["answer"],
                    "rating": "up",
                    "department": item.get("department") or "",
                    "feedback_id": item["id"],
                    "comment": "",
                }
            )
    return out


__all__ = [
    "NearDuplicateError",
    "VALID_RATINGS",
    "VALID_STATUSES",
    "apply_feedback_to_kb",
    "create_feedback",
    "dismiss_feedback",
    "export_preference_pairs",
    "get_feedback",
    "get_feedback_for_message",
    "list_feedback",
    "list_feedback_for_session",
]
