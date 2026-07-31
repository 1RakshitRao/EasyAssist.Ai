"""Append-only audit event store + training row helpers."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.audit.db import connect, init_audit_db

logger = logging.getLogger(__name__)
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Insert one immutable audit row. Returns the stored row (with id/timestamp)."""
    init_audit_db()
    row = dict(event)
    row.setdefault("id", str(uuid.uuid4()))
    row.setdefault("timestamp", _now())
    issues = row.get("score_issues") or row.get("score_issues_json") or []
    if isinstance(issues, list):
        issues_json = json.dumps(issues)
    else:
        issues_json = str(issues or "[]")
    sources = row.get("sources") or row.get("sources_json") or []
    if isinstance(sources, list):
        sources_json = json.dumps(sources)
    else:
        sources_json = str(sources or "[]")

    with _lock:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (
                    id, timestamp, user_id, user_email, user_role,
                    query, intent, department, severity, model_used, model_role,
                    input_tokens, output_tokens, cost_usd, from_cache, context_used,
                    prompt_score, score_issues_json, improved_query,
                    latency_ms, answer_length, sources_json, ticket_id
                ) VALUES (
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?
                )
                """,
                (
                    row["id"],
                    row["timestamp"],
                    row.get("user_id"),
                    (row.get("user_email") or "").lower(),
                    row.get("user_role"),
                    row.get("query") or "",
                    row.get("intent") or "helpdesk_query",
                    row.get("department"),
                    row.get("severity"),
                    row.get("model_used"),
                    row.get("model_role"),
                    int(row.get("input_tokens") or 0),
                    int(row.get("output_tokens") or 0),
                    float(row.get("cost_usd") or 0),
                    1 if row.get("from_cache") else 0,
                    1 if row.get("context_used") else 0,
                    row.get("prompt_score"),
                    issues_json,
                    row.get("improved_query"),
                    float(row.get("latency_ms") or 0),
                    int(row.get("answer_length") or 0),
                    sources_json,
                    row.get("ticket_id"),
                ),
            )
            conn.commit()
    logger.info(
        "audit append email=%s score=%s cost=%.6f cache=%s",
        row.get("user_email"),
        row.get("prompt_score"),
        float(row.get("cost_usd") or 0),
        bool(row.get("from_cache")),
    )
    return row


def _row_to_dict(row: Any) -> Dict[str, Any]:
    d = dict(row)
    d["from_cache"] = bool(d.get("from_cache"))
    d["context_used"] = bool(d.get("context_used"))
    try:
        d["score_issues"] = json.loads(d.get("score_issues_json") or "[]")
    except json.JSONDecodeError:
        d["score_issues"] = []
    try:
        d["sources"] = json.loads(d.get("sources_json") or "[]")
    except json.JSONDecodeError:
        d["sources"] = []
    return d


def list_user_queries(email: str, limit: int = 50) -> List[Dict[str, Any]]:
    init_audit_db()
    key = (email or "").strip().lower()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM audit_events
            WHERE user_email = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (key, int(limit)),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def recent_scores(email: str, window: int) -> List[int]:
    init_audit_db()
    key = (email or "").strip().lower()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT prompt_score FROM audit_events
            WHERE user_email = ? AND prompt_score IS NOT NULL
              AND intent != 'restricted'
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (key, int(window)),
        ).fetchall()
    return [int(r["prompt_score"]) for r in rows if r["prompt_score"] is not None]


def user_summaries() -> List[Dict[str, Any]]:
    init_audit_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT
                e.user_email AS user_email,
                MAX(e.user_role) AS user_role,
                COUNT(*) AS queries,
                SUM(CASE WHEN e.from_cache = 1 THEN 1 ELSE 0 END) AS cache_hits,
                SUM(e.input_tokens + e.output_tokens) AS total_tokens,
                SUM(e.cost_usd) AS total_cost,
                AVG(CASE WHEN e.prompt_score IS NOT NULL THEN e.prompt_score END) AS avg_score
            FROM audit_events e
            GROUP BY e.user_email
            ORDER BY total_cost DESC
            """
        ).fetchall()
        training = {
            r["user_email"]: dict(r)
            for r in conn.execute("SELECT * FROM user_training").fetchall()
        }

    out: List[Dict[str, Any]] = []
    for r in rows:
        email = r["user_email"]
        t = training.get(email) or {}
        queries = int(r["queries"] or 0)
        cache_hits = int(r["cache_hits"] or 0)
        avg = float(r["avg_score"] or t.get("rolling_avg_score") or 0)
        restricted = bool(t.get("access_restricted"))
        warning = t.get("warning_sent_at")
        if restricted:
            status = "restricted"
        elif warning and not t.get("training_completed_at"):
            status = "training"
        else:
            status = "good"
        out.append(
            {
                "user_email": email,
                "user_role": r["user_role"],
                "queries": queries,
                "cache_hits": cache_hits,
                "cache_hit_rate": round((cache_hits / queries) * 100, 1) if queries else 0.0,
                "total_tokens": int(r["total_tokens"] or 0),
                "total_cost_usd": round(float(r["total_cost"] or 0), 6),
                "avg_cost_per_query": round(float(r["total_cost"] or 0) / queries, 6)
                if queries
                else 0.0,
                "avg_prompt_score": round(avg, 2) if avg else 0.0,
                "status": status,
                "warning_sent_at": t.get("warning_sent_at"),
                "training_completed_at": t.get("training_completed_at"),
                "access_restricted": restricted,
            }
        )
    return out


def system_summary() -> Dict[str, Any]:
    init_audit_db()
    users = user_summaries()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_queries,
                SUM(cost_usd) AS total_cost,
                SUM(CASE WHEN from_cache = 1 THEN 1 ELSE 0 END) AS cache_hits
            FROM audit_events
            """
        ).fetchone()
        by_dept = conn.execute(
            """
            SELECT department, SUM(cost_usd) AS cost
            FROM audit_events
            WHERE department IS NOT NULL AND department != ''
            GROUP BY department
            ORDER BY cost DESC
            """
        ).fetchall()

    total_q = int(row["total_queries"] or 0)
    total_cost = float(row["total_cost"] or 0)
    cache_hits = int(row["cache_hits"] or 0)
    biggest = users[0] if users else None
    most_expensive_dept = None
    if by_dept:
        most_expensive_dept = {
            "department": by_dept[0]["department"],
            "cost_usd": round(float(by_dept[0]["cost"] or 0), 6),
        }
    # Approximate cache savings: assume cached queries would have cost avg non-cache
    with connect() as conn:
        non_cache = conn.execute(
            """
            SELECT AVG(cost_usd) AS avg_cost FROM audit_events WHERE from_cache = 0
            """
        ).fetchone()
    avg_non = float(non_cache["avg_cost"] or 0) if non_cache else 0.0
    cache_savings = round(cache_hits * avg_non, 6)

    return {
        "total_queries": total_q,
        "total_cost_usd": round(total_cost, 6),
        "cache_hits": cache_hits,
        "cache_hit_rate": round((cache_hits / total_q) * 100, 1) if total_q else 0.0,
        "cache_savings_usd": cache_savings,
        "biggest_spender": biggest,
        "most_expensive_dept": most_expensive_dept,
        "users": users,
    }


def get_training(email: str) -> Optional[Dict[str, Any]]:
    init_audit_db()
    key = (email or "").strip().lower()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM user_training WHERE user_email = ?", (key,)
        ).fetchone()
    return dict(row) if row else None


def upsert_training(email: str, **fields: Any) -> Dict[str, Any]:
    init_audit_db()
    key = (email or "").strip().lower()
    with _lock:
        with connect() as conn:
            existing = conn.execute(
                "SELECT * FROM user_training WHERE user_email = ?", (key,)
            ).fetchone()
            if not existing:
                conn.execute(
                    """
                    INSERT INTO user_training (
                        user_email, rolling_avg_score, queries_scored,
                        warning_sent_at, training_completed_at,
                        access_restricted, restriction_lifted_at
                    ) VALUES (?, 0, 0, NULL, NULL, 0, NULL)
                    """,
                    (key,),
                )
            allowed = {
                "rolling_avg_score",
                "queries_scored",
                "warning_sent_at",
                "training_completed_at",
                "access_restricted",
                "restriction_lifted_at",
            }
            updates = {k: v for k, v in fields.items() if k in allowed}
            if "access_restricted" in updates:
                updates["access_restricted"] = 1 if updates["access_restricted"] else 0
            if updates:
                sets = ", ".join(f"{k} = ?" for k in updates)
                conn.execute(
                    f"UPDATE user_training SET {sets} WHERE user_email = ?",
                    (*updates.values(), key),
                )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM user_training WHERE user_email = ?", (key,)
            ).fetchone()
    data = dict(row)
    data["access_restricted"] = bool(data.get("access_restricted"))
    return data
