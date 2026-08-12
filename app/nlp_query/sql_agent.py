"""Layer 2 — SQL Agent: generate, validate, execute read-only SELECT."""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Set

from app.audit.db import audit_db_path, init_audit_db
from app.config import get_settings
from app.llm.client import complete, resolve_answer_model
from app.nlp_query.classify_facts import FactsClassification, classify_company_facts
from app.nlp_query.rules import ALL_NLP_TABLES, MAX_RESULT_ROWS, MUTATING_SQL_KEYWORDS

logger = logging.getLogger(__name__)

_TABLE_SCHEMAS: Dict[str, str] = {
    "company_facts": (
        "company_facts(id TEXT, category TEXT, name TEXT, description TEXT, "
        "detail_1 TEXT, detail_2 TEXT, active INTEGER, created_at TEXT, details TEXT) "
        "-- categories: clients|services|locations|products|team|partnerships; "
        "details is JSON with rich attributes"
    ),
    "audit_events": (
        "audit_events(id TEXT, timestamp TEXT, user_id TEXT, user_email TEXT, "
        "user_role TEXT, query TEXT, intent TEXT, department TEXT, severity TEXT, "
        "model_used TEXT, input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL, "
        "from_cache INTEGER, prompt_score INTEGER, latency_ms REAL, ticket_id TEXT)"
    ),
    "chat_messages": (
        "chat_messages(id TEXT, session_id TEXT, user_email TEXT, role TEXT, "
        "content TEXT, created_at TEXT, department TEXT, cost_usd REAL)"
    ),
    "chat_sessions": (
        "chat_sessions(session_id TEXT, user_email TEXT, title TEXT, "
        "created_at TEXT, updated_at TEXT)"
    ),
    "app_users": (
        "app_users(id TEXT, email TEXT, name TEXT, role TEXT, active INTEGER)"
    ),
    "kb_stats": (
        "kb_stats(department TEXT, doc_count INTEGER, updated_at TEXT)"
    ),
}


@dataclass
class SqlResult:
    ok: bool
    sql: str = ""
    sql_formatted: str = ""
    columns: List[str] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=list)
    error: str = ""
    model_used: str = ""
    token_usage: Dict[str, int] = field(default_factory=dict)


_SQL_CLAUSE_KEYWORDS = (
    "SELECT",
    "FROM",
    "WHERE",
    "AND",
    "OR",
    "ORDER BY",
    "GROUP BY",
    "HAVING",
    "LIMIT",
    "LEFT JOIN",
    "RIGHT JOIN",
    "INNER JOIN",
    "JOIN",
    "ON",
    "UNION",
    "EXCEPT",
    "INTERSECT",
)


def format_sql(sql: str) -> str:
    """
    Format SQL for display: start a new line when a clause keyword appears,
    keeping the keyword and its content on the same line.

    Example:
      SELECT name, description FROM company_facts WHERE active = 1 AND category = 'products'
    →
      SELECT name, description
      FROM company_facts
      WHERE active = 1
        AND category = 'products'
    """
    flat = re.sub(r"\s+", " ", (sql or "").strip())
    if not flat:
        return ""

    # Break before clause keywords (longer phrases first). Keep keyword + rest together.
    pattern = r"\b(" + "|".join(
        re.escape(k) for k in sorted(_SQL_CLAUSE_KEYWORDS, key=len, reverse=True)
    ) + r")\b"
    spaced = re.sub(pattern, r"\n\1", flat, flags=re.IGNORECASE)

    keyword_lookup = {k.upper(): k for k in _SQL_CLAUSE_KEYWORDS}
    lines: List[str] = []
    for raw_line in spaced.strip().split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        m = re.match(
            r"^(SELECT|FROM|WHERE|AND|OR|ORDER BY|GROUP BY|HAVING|LIMIT|"
            r"LEFT JOIN|RIGHT JOIN|INNER JOIN|JOIN|ON|UNION|EXCEPT|INTERSECT)"
            r"\b(.*)$",
            line,
            re.IGNORECASE,
        )
        if m:
            kw = keyword_lookup.get(m.group(1).upper(), m.group(1).upper())
            rest = m.group(2).rstrip()
            # Normalize leading space after keyword
            if rest and not rest.startswith(" "):
                rest = " " + rest
            combined = f"{kw}{rest}".rstrip()
            if kw in ("AND", "OR"):
                lines.append("  " + combined)
            else:
                lines.append(combined)
        else:
            lines.append(line)

    return "\n".join(lines)


def schema_context(allowed_tables: Sequence[str]) -> str:
    parts = []
    for t in allowed_tables:
        if t in _TABLE_SCHEMAS:
            parts.append(_TABLE_SCHEMAS[t])
    return "\n".join(parts)


def _normalize_q(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _is_company_facts_question(question: str) -> bool:
    q = _normalize_q(question)
    # Never treat write/destructive intents as facts lookups
    mutating = (
        "drop ",
        "delete ",
        "insert ",
        "update ",
        "truncate ",
        "alter ",
        "create ",
    )
    if any(m in q for m in mutating):
        return False
    hints = (
        "client",
        "customer",
        "service",
        "product",
        "location",
        "office",
        "hq",
        "ampcus",
        "company_facts",
        "what do we offer",
        "who are our",
        "team",
        "who leads",
        "head of",
        "partner",
        "partnership",
        "vendor",
    )
    return any(h in q for h in hints)


def _user_question_only(text: str) -> str:
    """Strip Access-layer Constraints so rewrite examples cannot pollute classify."""
    raw = (text or "").strip()
    if not raw:
        return ""
    # rewrite_question appends "\n\nConstraints: ..."
    parts = re.split(r"\n\s*Constraints:\s*", raw, maxsplit=1)
    return parts[0].strip()


def _team_role_filter(q: str) -> str | None:
    """Return a LIKE fragment for a specific role question, else None."""
    role_patterns: tuple[tuple[tuple[str, ...], str], ...] = (
        (("ceo", "group ceo", "chief executive", "founder"), "%group ceo%"),
        (("coo", "chief operating officer"), "%chief operating officer%"),
        (("group president",), "%group president%"),
        (("cro", "chief revenue officer"), "%chief revenue officer%"),
        (("chief forensics",), "%chief forensics%"),
        (("human resources", "head of hr", "chro", "hr manager"), "%human resources%"),
        (("cto", "chief technology officer"), "%chief technology%"),
        (("head of compliance", "compliance lead"), "%head of compliance%"),
        (("vp engineering", "vice president of engineering", "vice president engineering"),
         "%vp engineering%"),
        (("head of legal", "general counsel"), "%head of legal%"),
        (("head of hr", "head of human resources"), "%head of hr%"),
        (
            ("head of customer success", "customer success lead"),
            "%head of customer success%",
        ),
    )
    for triggers, like in role_patterns:
        if any(t in q for t in triggers):
            return like
    return None


def _wants_singular_answer(q: str) -> bool:
    """True when the question is asking for one person/thing, not a full list."""
    if any(
        p in q
        for p in (
            "who are",
            "list ",
            "list our",
            "what are our",
            "which are",
            "all our",
            "top client",
            "top clients",
        )
    ):
        return False
    return bool(
        re.search(r"\bwho is\b", q)
        or re.search(r"\bwhat is\b", q)
        or re.search(r"\bwho leads\b", q)
        or "oldest" in q
        or "newest" in q
    )


def heuristic_company_facts_sql(question: str) -> str:
    """Deterministic SELECT using a single classified category / entity."""
    user_q = _user_question_only(question)
    q = _normalize_q(user_q)
    base = (
        "SELECT name, description, category, detail_1, detail_2, details "
        "FROM company_facts WHERE active = 1"
    )
    clf: FactsClassification = classify_company_facts(user_q)
    logger.info(
        "facts classify category=%s entity=%s reason=%s confidence=%s q=%r",
        clf.category,
        clf.entity_name,
        clf.reason,
        clf.confidence,
        user_q[:120],
    )

    since_ord = (
        "CAST(json_extract(details, '$.since_year') AS INTEGER)"
    )

    if clf.entity_name:
        safe = clf.entity_name.replace("'", "''")
        return (
            f"{base} AND lower(name) LIKE '%{safe}%' "
            f"ORDER BY category, name LIMIT 10"
        )

    if clf.category:
        where = f"{base} AND category = '{clf.category}'"
        # Specific team role (CTO, Head of X, …) — do not dump the whole roster
        if clf.category == "team":
            role_like = _team_role_filter(q)
            if role_like:
                safe_like = role_like.replace("'", "''")
                return (
                    f"{where} AND ("
                    f"lower(description) LIKE '{safe_like}' "
                    f"OR lower(detail_1) LIKE '{safe_like}' "
                    f"OR lower(coalesce(json_extract(details, '$.title'), '')) "
                    f"LIKE '{safe_like}'"
                    f") ORDER BY name LIMIT 3"
                )
        # Temporal / ranking intents for clients (and similar)
        if any(w in q for w in ("oldest", "earliest", "longest running", "first client")):
            return (
                f"{where} ORDER BY CASE WHEN {since_ord} IS NULL THEN 9999 "
                f"ELSE {since_ord} END ASC, name LIMIT 5"
            )
        if any(w in q for w in ("newest", "latest", "most recent", "newest client")):
            return (
                f"{where} ORDER BY CASE WHEN {since_ord} IS NULL THEN 0 "
                f"ELSE {since_ord} END DESC, name LIMIT 5"
            )
        if clf.category == "clients" and any(
            w in q for w in ("top client", "top clients", "strategic")
        ):
            # Prefer Strategic / Enterprise tiers when asking for "top"
            return (
                f"{where} ORDER BY CASE "
                f"WHEN lower(coalesce(json_extract(details, '$.tier'), '')) "
                f"= 'strategic' THEN 0 "
                f"WHEN lower(coalesce(json_extract(details, '$.tier'), '')) "
                f"= 'enterprise' THEN 1 "
                f"ELSE 2 END, name LIMIT 20"
            )
        limit = 5 if _wants_singular_answer(q) else 20
        return f"{where} ORDER BY name LIMIT {limit}"

    return f"{base} ORDER BY category, name LIMIT 40"


def _extract_sql(text: str) -> str:
    raw = (text or "").strip()
    fence = re.search(r"```(?:sql)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()
    # Take first statement-ish line block
    raw = raw.strip().rstrip(";")
    return raw.strip()


def validate_sql(sql: str, allowed_tables: Set[str]) -> str | None:
    """Return error message or None if OK."""
    if not sql or not sql.strip():
        return "Empty SQL"
    cleaned = sql.strip()
    if ";" in cleaned.rstrip(";"):
        return "Multiple statements are not allowed"
    low = cleaned.lower()
    # Strip simple string literals for keyword scan (best-effort)
    scan = re.sub(r"'([^']|'')*'", "''", low)
    for kw in MUTATING_SQL_KEYWORDS:
        if re.search(rf"\b{re.escape(kw)}\b", scan):
            return f"Forbidden keyword: {kw}"
    if not (scan.lstrip().startswith("select") or scan.lstrip().startswith("with")):
        return "Only SELECT queries are allowed"
    # Table references: FROM / JOIN
    mentioned = set(re.findall(r"\b(?:from|join)\s+([a-z_][a-z0-9_]*)", scan))
    # Also catch table.column without from in WITH — still check known bad tables
    for t in ALL_NLP_TABLES:
        if re.search(rf"\b{re.escape(t)}\b", scan) and t not in allowed_tables:
            return f"Table not allowed for this role: {t}"
    for t in mentioned:
        if t not in allowed_tables:
            return f"Unknown or disallowed table: {t}"
    if not mentioned and "company_facts" in allowed_tables and "select" in scan:
        # Allow SELECT without FROM only for constants — rare; require a table
        if " from " not in f" {scan} ":
            return "Query must select FROM an allowed table"
    return None


def enforce_limit(sql: str, limit: int = MAX_RESULT_ROWS) -> str:
    low = sql.lower()
    if re.search(r"\blimit\s+\d+", low):
        def _cap(m: re.Match) -> str:
            n = int(m.group(1))
            return f"LIMIT {min(n, limit)}"

        return re.sub(r"\blimit\s+(\d+)", _cap, sql, flags=re.IGNORECASE)
    return f"{sql.rstrip()} LIMIT {limit}"


def generate_sql(
    rewritten_question: str, allowed_tables: Sequence[str]
) -> tuple[str, str, Dict[str, int]]:
    """Return (sql, model_used, token_usage)."""
    tables = set(allowed_tables)
    # Prefer deterministic SQL for business-fact questions (avoids LLM inventing joins)
    if "company_facts" in tables and (
        tables == {"company_facts"} or _is_company_facts_question(rewritten_question)
    ):
        return heuristic_company_facts_sql(rewritten_question), "heuristic", {}

    settings = get_settings()
    schema = schema_context(allowed_tables)
    system = (
        "You are a SQLite SQL generator for Ampcus Helpdesk analytics. "
        "Return ONLY one SQLite SELECT statement. No markdown, no explanation. "
        "Use only the provided tables/columns. Never invent columns or aliases. "
        "Never JOIN unless required. Prefer simple single-table SELECTs. "
        "Never modify data."
    )
    user_msg = (
        f"Allowed schema:\n{schema}\n\n"
        f"Question (already scoped):\n{rewritten_question}\n\n"
        "SQL:"
    )
    # Offline / no key: heuristic for company_facts
    if settings.llm_provider.lower() == "anthropic" and not settings.anthropic_api_key:
        if "company_facts" in tables:
            return heuristic_company_facts_sql(rewritten_question), "heuristic", {}
        fallback = (
            "SELECT user_email, SUM(cost_usd) AS total_cost "
            "FROM audit_events GROUP BY user_email ORDER BY total_cost DESC LIMIT 20"
            if "audit_events" in tables
            else "SELECT 1 WHERE 0"
        )
        return fallback, "heuristic", {}
    model = resolve_answer_model("routine", preference="routine")
    try:
        result = complete(
            model=model,
            system=system,
            user_content=user_msg,
            max_tokens=400,
        )
        return (
            _extract_sql(result.text),
            result.model or model,
            dict(result.token_usage or {}),
        )
    except Exception:
        logger.exception("SQL generation failed")
        raise


def connect_readonly() -> sqlite3.Connection:
    init_audit_db()
    path = audit_db_path()
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=5.0)
    except sqlite3.Error:
        conn = sqlite3.connect(str(path), check_same_thread=False, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")
    except sqlite3.Error:
        pass
    return conn


def execute_sql(sql: str, allowed_tables: Set[str]) -> SqlResult:
    err = validate_sql(sql, allowed_tables)
    if err:
        return SqlResult(ok=False, sql=sql, sql_formatted=format_sql(sql), error=err)
    limited = enforce_limit(sql)
    err2 = validate_sql(limited, allowed_tables)
    if err2:
        return SqlResult(
            ok=False, sql=limited, sql_formatted=format_sql(limited), error=err2
        )
    try:
        with connect_readonly() as conn:
            cur = conn.execute(limited)
            cols = [d[0] for d in (cur.description or [])]
            fetched = cur.fetchmany(MAX_RESULT_ROWS)
            rows = [dict(zip(cols, row)) for row in fetched]
        return SqlResult(
            ok=True,
            sql=limited,
            sql_formatted=format_sql(limited),
            columns=cols,
            rows=rows,
        )
    except Exception as exc:
        logger.warning("SQL execute failed: %s", exc)
        return SqlResult(
            ok=False,
            sql=limited,
            sql_formatted=format_sql(limited),
            error=str(exc),
        )


def run_sql_agent(rewritten_question: str, allowed_tables: Sequence[str]) -> SqlResult:
    tables = set(allowed_tables)
    model_used = ""
    token_usage: Dict[str, int] = {}
    try:
        sql, model_used, token_usage = generate_sql(
            rewritten_question, allowed_tables
        )
    except Exception as exc:
        if "company_facts" in tables:
            result = execute_sql(
                heuristic_company_facts_sql(rewritten_question), tables
            )
            result.model_used = "heuristic"
            return result
        return SqlResult(ok=False, error=f"SQL generation failed: {exc}")

    result = execute_sql(sql, tables)
    result.model_used = model_used
    result.token_usage = dict(token_usage or {})
    if not result.ok and "company_facts" in tables and _is_company_facts_question(
        rewritten_question
    ):
        fallback = execute_sql(heuristic_company_facts_sql(rewritten_question), tables)
        if fallback.ok:
            fallback.model_used = model_used or "heuristic"
            fallback.token_usage = dict(token_usage or {})
            return fallback
    return result
