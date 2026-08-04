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

CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    user_email TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_email_updated
ON chat_sessions(user_email, updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_email TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    department TEXT,
    cost_usd REAL
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session_created
ON chat_messages(session_id, created_at);

CREATE TABLE IF NOT EXISTS company_facts (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    detail_1 TEXT,
    detail_2 TEXT,
    active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    details TEXT
);

CREATE INDEX IF NOT EXISTS idx_company_facts_category
ON company_facts(category, active);

CREATE TABLE IF NOT EXISTS kb_stats (
    department TEXT PRIMARY KEY,
    doc_count INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    name TEXT,
    role TEXT NOT NULL,
    active INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_app_users_email
ON app_users(email);

CREATE TABLE IF NOT EXISTS nlp_query_logs (
    id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    user_id TEXT,
    user_email TEXT,
    user_role TEXT,
    question TEXT NOT NULL,
    sql_text TEXT,
    answer TEXT,
    allowed INTEGER NOT NULL DEFAULT 0,
    block_kind TEXT,
    row_count INTEGER,
    session_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_nlp_query_logs_ts
ON nlp_query_logs(timestamp DESC);

CREATE TABLE IF NOT EXISTS chat_documents (
    doc_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_email TEXT NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT,
    char_count INTEGER DEFAULT 0,
    text TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    stored_path TEXT,
    preview_kind TEXT,
    text_expires_at TEXT,
    file_expires_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_documents_session
ON chat_documents(session_id);

CREATE INDEX IF NOT EXISTS idx_chat_documents_expires
ON chat_documents(expires_at);
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
            _migrate_chat_documents(conn)
            conn.commit()
        _initialized = True
        logger.info("Audit SQLite ready path=%s", path)


def _migrate_chat_documents(conn: sqlite3.Connection) -> None:
    info = conn.execute("PRAGMA table_info(chat_documents)").fetchall()
    if not info:
        return
    cols = {r[1] for r in info}
    alter = []
    if "stored_path" not in cols:
        alter.append("ALTER TABLE chat_documents ADD COLUMN stored_path TEXT")
    if "preview_kind" not in cols:
        alter.append("ALTER TABLE chat_documents ADD COLUMN preview_kind TEXT")
    if "text_expires_at" not in cols:
        alter.append("ALTER TABLE chat_documents ADD COLUMN text_expires_at TEXT")
    if "file_expires_at" not in cols:
        alter.append("ALTER TABLE chat_documents ADD COLUMN file_expires_at TEXT")
    for sql in alter:
        conn.execute(sql)

    # Older builds had text TEXT NOT NULL; dual-TTL purge needs nullable text.
    text_notnull = next((int(r[3]) for r in info if r[1] == "text"), 0)
    if text_notnull:
        conn.executescript(
            """
            CREATE TABLE chat_documents_new (
                doc_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                user_email TEXT NOT NULL,
                filename TEXT NOT NULL,
                content_type TEXT,
                char_count INTEGER DEFAULT 0,
                text TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                stored_path TEXT,
                preview_kind TEXT,
                text_expires_at TEXT,
                file_expires_at TEXT
            );
            INSERT INTO chat_documents_new (
                doc_id, session_id, user_email, filename, content_type,
                char_count, text, created_at, expires_at,
                stored_path, preview_kind, text_expires_at, file_expires_at
            )
            SELECT
                doc_id, session_id, user_email, filename, content_type,
                char_count, text, created_at, expires_at,
                stored_path, preview_kind, text_expires_at, file_expires_at
            FROM chat_documents;
            DROP TABLE chat_documents;
            ALTER TABLE chat_documents_new RENAME TO chat_documents;
            CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_documents_session
            ON chat_documents(session_id);
            CREATE INDEX IF NOT EXISTS idx_chat_documents_expires
            ON chat_documents(expires_at);
            CREATE INDEX IF NOT EXISTS idx_chat_documents_file_expires
            ON chat_documents(file_expires_at);
            """
        )
        logger.info("Migrated chat_documents.text to nullable for dual TTL")

    # Index after columns exist (CREATE INDEX in _SCHEMA would fail on older DBs)
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_chat_documents_file_expires
        ON chat_documents(file_expires_at)
        """
    )
