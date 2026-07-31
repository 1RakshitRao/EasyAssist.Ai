"""Unit tests for rolling-average enforcement transitions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.audit.db import init_audit_db
from app.audit.enforcement import apply_enforcement, complete_training
from app.audit.store import append_event, get_training
from app.auth.users import create_user, get_user_by_email, set_access_restricted
from app.config import get_settings


@pytest.fixture()
def audit_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("USERS_PATH", str(tmp_path / "users.json"))
    monkeypatch.setenv("PROMPT_SCORE_WINDOW", "5")
    monkeypatch.setenv("PROMPT_SCORE_RESTRICT_AVG", "4.0")
    monkeypatch.setenv("PROMPT_TRAINING_GRACE_DAYS", "7")
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    init_audit_db()
    create_user(
        email="emp@ampcus.com",
        password="EmployeePass12!",
        role="employee",
        name="Emp",
    )
    yield
    get_settings.cache_clear()


def _score_events(email: str, scores: list[int]):
    for i, s in enumerate(scores):
        append_event(
            {
                "user_email": email,
                "user_id": "u1",
                "user_role": "employee",
                "query": f"q{i}",
                "intent": "helpdesk_query",
                "prompt_score": s,
                "score_issues": ["vague"],
                "improved_query": f"better {i}",
                "cost_usd": 0.001,
            }
        )


def test_warning_on_low_average(audit_env):
    email = "emp@ampcus.com"
    _score_events(email, [2, 2, 2, 2, 2])
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    result = apply_enforcement(email, now=now)
    assert result["status"] == "training"
    row = get_training(email)
    assert row["warning_sent_at"]
    assert not row["access_restricted"]


def test_restrict_after_grace(audit_env):
    email = "emp@ampcus.com"
    _score_events(email, [1, 1, 1, 1, 1])
    warn_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    apply_enforcement(email, now=warn_at)
    later = warn_at + timedelta(days=8)
    result = apply_enforcement(email, now=later)
    assert result["status"] == "restricted"
    user = get_user_by_email(email)
    assert user["access_restricted"] is True


def test_recover_clears_warning(audit_env):
    email = "emp@ampcus.com"
    _score_events(email, [2, 2, 2])
    apply_enforcement(email, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert get_training(email)["warning_sent_at"]
    _score_events(email, [9, 9, 9, 9, 9])
    result = apply_enforcement(email, now=datetime(2026, 1, 2, tzinfo=timezone.utc))
    assert result["status"] == "good"
    assert get_training(email)["warning_sent_at"] is None


def test_complete_training_lifts(audit_env):
    email = "emp@ampcus.com"
    set_access_restricted(email, True)
    from app.audit.store import upsert_training

    upsert_training(email, access_restricted=True, warning_sent_at="2026-01-01T00:00:00+00:00")
    complete_training(email)
    assert get_user_by_email(email)["access_restricted"] is False
    assert get_training(email)["training_completed_at"]
