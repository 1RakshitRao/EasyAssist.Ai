"""Rolling prompt-score enforcement: warn → grace → soft restrict."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from jose import JWTError, jwt

from app.audit.emailer import build_training_email, send_email
from app.audit.store import get_training, list_user_queries, recent_scores, upsert_training
from app.auth.users import get_user_by_email, is_admin_role, set_access_restricted
from app.config import get_settings

logger = logging.getLogger(__name__)


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def create_training_token(email: str, expires_days: int = 14) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(days=expires_days)
    payload = {
        "purpose": "training",
        "email": (email or "").strip().lower(),
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_training_token(token: str) -> str:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise ValueError("Invalid or expired training token") from exc
    if payload.get("purpose") != "training":
        raise ValueError("Invalid training token purpose")
    email = str(payload.get("email") or "").strip().lower()
    if not email:
        raise ValueError("Invalid training token email")
    return email


def training_page_url(email: str) -> str:
    """Legacy helper — training self-service page removed; link to main app."""
    settings = get_settings()
    return (settings.training_base_url or settings.app_base_url or "http://127.0.0.1:8080").rstrip("/")


def complete_training(email: str) -> Dict[str, Any]:
    """Clear restriction and mark training complete for email."""
    key = (email or "").strip().lower()
    now = datetime.now(timezone.utc).isoformat()
    row = upsert_training(
        key,
        access_restricted=False,
        training_completed_at=now,
        restriction_lifted_at=now,
        warning_sent_at=None,
    )
    set_access_restricted(key, False)
    logger.info("Training completed for %s", key)
    return row


def _bad_query_samples(email: str) -> List[Dict[str, Any]]:
    rows = list_user_queries(email, limit=20)
    samples: List[Dict[str, Any]] = []
    for r in rows:
        score = r.get("prompt_score")
        if score is None:
            continue
        if int(score) >= 7:
            continue
        samples.append(
            {
                "query": r.get("query"),
                "score": score,
                "issues": r.get("score_issues") or [],
                "improved_query": r.get("improved_query"),
            }
        )
        if len(samples) >= 5:
            break
    return samples


def apply_enforcement(email: str, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """
    Recompute rolling average and run warn / restrict side-effects.
    Returns {rolling_avg, queries_scored, status, training_row}.
    """
    settings = get_settings()
    key = (email or "").strip().lower()
    user = get_user_by_email(key)
    if user and is_admin_role(user.get("role")):
        row = get_training(key) or upsert_training(key)
        return {
            "rolling_avg": 0.0,
            "queries_scored": 0,
            "status": "good",
            "training_row": row,
        }

    clock = now or datetime.now(timezone.utc)
    window = max(1, int(settings.prompt_score_window))
    threshold = float(settings.prompt_score_restrict_avg)
    grace_days = int(settings.prompt_training_grace_days)

    scores = recent_scores(key, window)
    if not scores:
        row = get_training(key) or upsert_training(key)
        return {
            "rolling_avg": 0.0,
            "queries_scored": 0,
            "status": "good",
            "training_row": row,
        }

    avg = sum(scores) / len(scores)
    upsert_training(key, rolling_avg_score=round(avg, 3), queries_scored=len(scores))
    row = get_training(key) or {}

    # Recovered after warning without restriction
    if avg >= threshold:
        if row.get("warning_sent_at") and not row.get("access_restricted"):
            upsert_training(key, warning_sent_at=None)
            row = get_training(key) or row
        return {
            "rolling_avg": round(avg, 3),
            "queries_scored": len(scores),
            "status": "restricted" if row.get("access_restricted") else "good",
            "training_row": row,
        }

    # Below threshold
    warning_at = _parse_ts(row.get("warning_sent_at"))
    if not warning_at:
        url = training_page_url(key)
        subject, body = build_training_email(
            user_email=key,
            bad_queries=_bad_query_samples(key),
            training_url=url,
        )
        send_email(to=key, subject=subject, body=body)
        upsert_training(key, warning_sent_at=clock.isoformat())
        row = get_training(key) or row
        return {
            "rolling_avg": round(avg, 3),
            "queries_scored": len(scores),
            "status": "training",
            "training_row": row,
        }

    # Grace expired and still poor → restrict
    if not row.get("access_restricted") and not row.get("training_completed_at"):
        if clock - warning_at >= timedelta(days=grace_days):
            upsert_training(key, access_restricted=True)
            set_access_restricted(key, True)
            row = get_training(key) or row
            logger.info("Access restricted for %s avg=%.2f", key, avg)
            return {
                "rolling_avg": round(avg, 3),
                "queries_scored": len(scores),
                "status": "restricted",
                "training_row": row,
            }

    status = "restricted" if row.get("access_restricted") else "training"
    return {
        "rolling_avg": round(avg, 3),
        "queries_scored": len(scores),
        "status": status,
        "training_row": row,
    }
