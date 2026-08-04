"""Sync helpers — app_users mirror + kb_stats from Chroma."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.audit.db import connect, init_audit_db

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sync_app_users(users: List[Dict[str, Any]] | None = None) -> int:
    """Replace app_users mirror from users.json (or provided list)."""
    init_audit_db()
    if users is None:
        from app.auth.users import list_users

        users = list_users()
    with connect() as conn:
        conn.execute("DELETE FROM app_users")
        for u in users:
            conn.execute(
                """
                INSERT INTO app_users (id, email, name, role, active)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(u.get("id") or ""),
                    str(u.get("email") or "").lower(),
                    str(u.get("name") or ""),
                    str(u.get("role") or "employee"),
                    1 if u.get("active", True) else 0,
                ),
            )
        conn.commit()
    logger.info("Synced app_users count=%d", len(users))
    return len(users)


def refresh_kb_stats(counts: Dict[str, int] | None = None) -> Dict[str, int]:
    """Upsert kb_stats from Chroma collection counts."""
    init_audit_db()
    if counts is None:
        try:
            from app.rag.chroma_store import get_store

            counts = get_store().collection_counts()
        except Exception:
            logger.warning("kb_stats refresh skipped — chroma unavailable", exc_info=True)
            counts = {}
    now = _now()
    with connect() as conn:
        for dept, n in (counts or {}).items():
            conn.execute(
                """
                INSERT INTO kb_stats (department, doc_count, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(department) DO UPDATE SET
                    doc_count = excluded.doc_count,
                    updated_at = excluded.updated_at
                """,
                (str(dept).lower(), int(n or 0), now),
            )
        conn.commit()
    return dict(counts or {})
