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
    updated_at TEXT NOT NULL,
    pending_ticket_json TEXT,
    pending_reservation_json TEXT
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

CREATE TABLE IF NOT EXISTS employees (
    email TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    employee_id TEXT UNIQUE,
    department TEXT NOT NULL,
    role_title TEXT NOT NULL,
    manager_email TEXT,
    office_location TEXT,
    joining_date TEXT NOT NULL,
    onboarding_complete INTEGER DEFAULT 0,
    onboarding_started_at TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL,
    active INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_employees_joining_complete
ON employees(joining_date, onboarding_complete);

CREATE TABLE IF NOT EXISTS onboarding_tasks (
    id TEXT PRIMARY KEY,
    employee_email TEXT NOT NULL,
    task_key TEXT NOT NULL,
    task_title TEXT NOT NULL,
    task_description TEXT,
    category TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    due_date TEXT,
    completed_at TEXT,
    reminder_count INTEGER DEFAULT 0,
    last_reminded_at TEXT,
    link_url TEXT,
    department_specific INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    FOREIGN KEY (employee_email) REFERENCES employees(email),
    UNIQUE (employee_email, task_key)
);

CREATE INDEX IF NOT EXISTS idx_onboarding_tasks_email_status
ON onboarding_tasks(employee_email, status);

CREATE INDEX IF NOT EXISTS idx_onboarding_tasks_email_category
ON onboarding_tasks(employee_email, category, sort_order);

CREATE TABLE IF NOT EXISTS onboarding_reminders (
    id TEXT PRIMARY KEY,
    employee_email TEXT NOT NULL,
    task_id TEXT,
    reminder_type TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    delivery_status TEXT DEFAULT 'sent',
    channel TEXT DEFAULT 'email',
    FOREIGN KEY (employee_email) REFERENCES employees(email)
);

CREATE INDEX IF NOT EXISTS idx_onboarding_reminders_email_sent
ON onboarding_reminders(employee_email, sent_at DESC);

CREATE TABLE IF NOT EXISTS guesthouses (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    address     TEXT NOT NULL,
    city        TEXT NOT NULL DEFAULT 'Bloomington',
    amenities   TEXT DEFAULT '[]',
    photos_json TEXT DEFAULT '[]',
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rooms (
    id             TEXT PRIMARY KEY,
    guesthouse_id  TEXT NOT NULL REFERENCES guesthouses(id),
    room_number    TEXT NOT NULL,
    room_name      TEXT NOT NULL,
    capacity       INTEGER NOT NULL DEFAULT 2,
    amenities      TEXT DEFAULT '[]',
    active         INTEGER NOT NULL DEFAULT 1,
    UNIQUE(guesthouse_id, room_number)
);

CREATE TABLE IF NOT EXISTS availability (
    id              TEXT PRIMARY KEY,
    room_id         TEXT NOT NULL REFERENCES rooms(id),
    date            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'available',
    reservation_id  TEXT,
    source          TEXT DEFAULT 'system',
    uploaded_by     TEXT,
    created_at      TEXT NOT NULL,
    UNIQUE(room_id, date)
);

CREATE TABLE IF NOT EXISTS reservations (
    id                   TEXT PRIMARY KEY,
    confirmation_number  TEXT NOT NULL UNIQUE,
    employee_email       TEXT NOT NULL,
    room_id              TEXT NOT NULL REFERENCES rooms(id),
    guesthouse_id        TEXT NOT NULL REFERENCES guesthouses(id),
    checkin_date         TEXT NOT NULL,
    checkout_date        TEXT NOT NULL,
    purpose              TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending_approval',
    created_at           TEXT NOT NULL,
    approved_at          TEXT,
    approved_by          TEXT,
    rejected_at          TEXT,
    rejected_by          TEXT,
    rejection_reason     TEXT,
    cancelled_at         TEXT,
    cancelled_by         TEXT,
    override_at          TEXT,
    override_by          TEXT,
    override_reason      TEXT,
    last_modified_at     TEXT,
    modification_count   INTEGER DEFAULT 0,
    auto_approve_at      TEXT,
    notified_48h         INTEGER DEFAULT 0,
    notified_checkin     INTEGER DEFAULT 0,
    notified_checkout    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reservation_audit (
    id               TEXT PRIMARY KEY,
    reservation_id   TEXT NOT NULL REFERENCES reservations(id),
    action           TEXT NOT NULL,
    performed_by     TEXT NOT NULL,
    reason           TEXT,
    previous_status  TEXT,
    new_status       TEXT,
    previous_dates   TEXT,
    timestamp        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_avail_room_date ON availability(room_id, date);
CREATE INDEX IF NOT EXISTS idx_reservations_employee ON reservations(employee_email);
CREATE INDEX IF NOT EXISTS idx_reservations_status ON reservations(status);
CREATE INDEX IF NOT EXISTS idx_reservations_dates ON reservations(checkin_date, checkout_date);
CREATE INDEX IF NOT EXISTS idx_audit_reservation ON reservation_audit(reservation_id);

CREATE TABLE IF NOT EXISTS office_printers (
    id TEXT PRIMARY KEY,
    office_location TEXT NOT NULL,
    printer_name TEXT NOT NULL,
    printer_ip TEXT NOT NULL,
    ipp_port INTEGER NOT NULL DEFAULT 631,
    ipp_path TEXT NOT NULL DEFAULT '/ipp/print',
    model TEXT,
    floor TEXT,
    notes TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_office_printers_location
ON office_printers(office_location, active);

CREATE TABLE IF NOT EXISTS conference_rooms (
    id TEXT PRIMARY KEY,
    office_location TEXT NOT NULL,
    room_name TEXT NOT NULL,
    room_email TEXT NOT NULL,
    capacity INTEGER NOT NULL DEFAULT 4,
    floor TEXT,
    av_equipment_json TEXT DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conference_rooms_office
ON conference_rooms(office_location, active);
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
            _migrate_chat_sessions(conn)
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


def _migrate_chat_sessions(conn: sqlite3.Connection) -> None:
    info = conn.execute("PRAGMA table_info(chat_sessions)").fetchall()
    if not info:
        return
    cols = {r[1] for r in info}
    if "pending_ticket_json" not in cols:
        conn.execute(
            "ALTER TABLE chat_sessions ADD COLUMN pending_ticket_json TEXT"
        )
        logger.info("Added chat_sessions.pending_ticket_json column")
    if "pending_reservation_json" not in cols:
        conn.execute(
            "ALTER TABLE chat_sessions ADD COLUMN pending_reservation_json TEXT"
        )
        logger.info("Added chat_sessions.pending_reservation_json column")
    if "pending_infrastructure_json" not in cols:
        conn.execute(
            "ALTER TABLE chat_sessions ADD COLUMN pending_infrastructure_json TEXT"
        )
        logger.info("Added chat_sessions.pending_infrastructure_json column")
