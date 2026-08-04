"""NLP query access rules — role tables, injection patterns, blocked keywords."""

from __future__ import annotations

from typing import Dict, FrozenSet, Set

# Tables the SQL agent may ever reference (whitelist universe)
ALL_NLP_TABLES: FrozenSet[str] = frozenset(
    {
        "company_facts",
        "audit_events",
        "chat_messages",
        "chat_sessions",
        "app_users",
        "kb_stats",
    }
)

# Two-tier map: employee/agent = business facts; admin = full ops
ROLE_ALLOWED_TABLES: Dict[str, FrozenSet[str]] = {
    "employee": frozenset({"company_facts"}),
    "agent": frozenset({"company_facts"}),
    "admin": ALL_NLP_TABLES,
}

MAX_RESULT_ROWS = 100

# Prompt-injection / override phrases (substring match, case-insensitive)
INJECTION_PATTERNS: tuple[str, ...] = (
    "ignore previous instructions",
    "ignore your rules",
    "ignore all rules",
    "forget your rules",
    "forget previous",
    "you are now",
    "pretend you are",
    "act as",
    "your new instructions",
    "disregard",
    "override",
    "system prompt",
    "jailbreak",
    "developer mode",
    "do anything now",
)

# Write / destructive intents — block for EVERY role (NLP is SELECT-only)
MUTATING_QUERY_PATTERNS: tuple[str, ...] = (
    "drop table",
    "drop database",
    "delete from",
    "insert into",
    "update ",
    "truncate ",
    "alter table",
    "create table",
    "attach database",
    "detach database",
    "pragma ",
    "vacuum",
    "reindex",
)

# Meta / schema probes — block for everyone at Access layer
META_QUERY_PATTERNS: tuple[str, ...] = (
    "what tables",
    "which tables",
    "show me the schema",
    "database schema",
    "list all columns",
    "show columns",
    "what columns",
    "sqlite_master",
    "information_schema",
    "show me your prompt",
    "what is your system prompt",
    "how are you implemented",
    "what sql did you",
    "show me the sql",
    "dump the database",
    "pragma table",
)

# Operational / sensitive topics employees+agents must not ask about
EMPLOYEE_BLOCKED_TOPICS: tuple[str, ...] = (
    "prompt score",
    "prompt scores",
    "cost_usd",
    "token usage",
    "tokens spent",
    "how much has each user",
    "user spent",
    "audit_log",
    "audit_events",
    "chat_messages",
    "chat history",
    "all users",
    "list users",
    "show users",
    "user emails",
    "email addresses",
    "cache hit",
    "escalation",
    "escalations",
    "ticket",
    "password",
    "secrets",
    "raw dump",
    "dump of",
    "bypass",
    "disable pii",
    "drop table",
    "delete from",
    "insert into",
    "update ",
    "truncate",
)

MUTATING_SQL_KEYWORDS: tuple[str, ...] = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "create",
    "truncate",
    "attach",
    "detach",
    "replace",
    "pragma",
    "vacuum",
    "reindex",
)

def allowed_tables_for_role(role: str) -> Set[str]:
    key = (role or "employee").strip().lower()
    return set(ROLE_ALLOWED_TABLES.get(key, ROLE_ALLOWED_TABLES["employee"]))


def is_admin_role(role: str) -> bool:
    return (role or "").strip().lower() == "admin"


def is_facts_only_role(role: str) -> bool:
    return not is_admin_role(role)
