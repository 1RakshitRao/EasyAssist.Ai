"""SQLite connection + schema bootstrap for audit log."""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_initialized = False

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    user_id TEXT,
    user_email TEXT NOT NULL,
    user_role TEXT,
    query TEXT NOT NULL,
    intent TEXT,
    department TEXT,
    severity TEXT,
    model_used TEXT,
    model_role TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0,
    from_cache INTEGER DEFAULT 0,
    context_used INTEGER DEFAULT 0,
    prompt_score INTEGER,
    score_issues_json TEXT,
    improved_query TEXT,
    latency_ms REAL DEFAULT 0,
    answer_length INTEGER DEFAULT 0,
    sources_json TEXT,
    ticket_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_email_ts
ON audit_events(user_email, timestamp DESC);

CREATE TABLE IF NOT EXISTS user_training (
    user_email TEXT PRIMARY KEY,
    rolling_avg_score REAL DEFAULT 0,
    queries_scored INTEGER DEFAULT 0,
    warning_sent_at TEXT,
    training_completed_at TEXT,
    access_restricted INTEGER DEFAULT 0,
    restriction_lifted_at TEXT
);
"""


def audit_db_path() -> Path:
    settings = get_settings()
    if settings.audit_db_path:
        path = Path(settings.audit_db_path).resolve()
    else:
        base = Path(settings.chroma_persist_dir).resolve().parent
        path = base / "audit.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(audit_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_audit_db() -> None:
    global _initialized
    with _lock:
        path = audit_db_path()
        with connect() as conn:
            conn.executescript(_SCHEMA)
            conn.commit()
        _initialized = True
        logger.info("Audit SQLite ready path=%s", path)
