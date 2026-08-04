"""Layer 3 — Output Agent: PII/scope checks + answer synthesis."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from app.config import get_settings
from app.llm.client import complete, resolve_answer_model
from app.nlp_query.rules import is_admin_role, is_facts_only_role
from app.nlp_query.sql_agent import SqlResult

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)

_PII_COLUMNS = frozenset(
    {
        "user_email",
        "email",
        "user_id",
        "password_hash",
        "password",
    }
)


@dataclass
class OutputDecision:
    allowed: bool
    answer: str
    reason: str = ""
    model_used: str = ""
    token_usage: Dict[str, int] = field(default_factory=dict)


def _row_has_email_values(rows: Sequence[Dict[str, Any]]) -> bool:
    for row in rows:
        for v in row.values():
            if isinstance(v, str) and _EMAIL_RE.search(v):
                return True
    return False


def _has_pii_columns(columns: Sequence[str]) -> bool:
    return any(c.lower() in _PII_COLUMNS for c in columns)


def scrub_rows_for_role(
    role: str, columns: List[str], rows: List[Dict[str, Any]]
) -> tuple[List[str], List[Dict[str, Any]], str | None]:
    """Return (cols, rows, block_reason). block_reason set if must refuse entirely."""
    if is_admin_role(role):
        return columns, rows, None

    # Facts-only roles: strip PII columns; block if emails remain in values
    safe_cols = [c for c in columns if c.lower() not in _PII_COLUMNS]
    safe_rows = [{k: r.get(k) for k in safe_cols} for r in rows]
    if _row_has_email_values(safe_rows):
        return safe_cols, [], "Result contained personal email data and was blocked."
    # Employees should not see huge raw dumps — cap for synthesis
    if len(safe_rows) > 20:
        safe_rows = safe_rows[:20]
    return safe_cols, safe_rows, None


def _format_rows_plaintext(columns: List[str], rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "(no rows)"
    lines = []
    for i, row in enumerate(rows, 1):
        parts = [f"{c}={row.get(c)}" for c in columns]
        lines.append(f"{i}. " + "; ".join(parts))
    return "\n".join(lines)


def synthesize_answer(
    *,
    role: str,
    original_question: str,
    columns: List[str],
    rows: List[Dict[str, Any]],
) -> tuple[str, str, Dict[str, int]]:
    """Return (answer, model_used, token_usage)."""
    settings = get_settings()
    plain = _format_rows_plaintext(columns, rows)
    if not rows:
        return (
            "I could not find matching company information for that question.",
            "",
            {},
        )

    if settings.llm_provider.lower() == "anthropic" and not settings.anthropic_api_key:
        # Deterministic offline synthesis for company_facts
        if "name" in columns:
            lines = []
            for r in rows[:10]:
                name = str(r.get("name") or "").strip()
                if not name:
                    continue
                desc = str(r.get("description") or "").strip()
                lines.append(f"- {name}" + (f" — {desc}" if desc else ""))
            if lines:
                return "Here is what I found:\n" + "\n".join(lines), "offline", {}
        return f"Here are the results:\n{plain[:1500]}", "offline", {}

    system = (
        "You are the Ampcus Helpdesk data answer assistant. "
        "Answer the user's question directly and briefly using only the result rows. "
        "Do not invent facts not present in the rows. "
        "Do not mention SQL, tables, or columns. "
        "Never claim that data was deleted, dropped, inserted, or modified — "
        "this pipeline is read-only and results are SELECT snapshots only. "
        "If the question asks for one person, name, role, or fact, answer with "
        "that only — do not list other unrelated rows even if they appear in the results. "
        "Only list multiple items when the question clearly asks for a list "
        "(e.g. who are our clients, what products do we have). "
        "For category=clients rows, call them clients or customers — "
        "never call them partners or partnerships. "
        "For category=partnerships rows, call them vendors or technology partners."
    )
    if is_facts_only_role(role):
        system += " Keep the answer high-level business information only."
    user_msg = (
        f"User question: {original_question}\n\n"
        f"Result rows ({len(rows)} total):\n{plain}\n\n"
        "Write a concise answer to the question only:"
    )
    model = resolve_answer_model("routine", preference="routine")
    try:
        result = complete(
            model=model,
            system=system,
            user_content=user_msg,
            max_tokens=350,
        )
        answer = (result.text or "").strip() or plain
        return answer, result.model or model, dict(result.token_usage or {})
    except Exception:
        logger.exception("Output synthesis failed")
        return f"Here are the results:\n{plain[:1500]}", model, {}


def review_output(
    *,
    role: str,
    original_question: str,
    sql_result: SqlResult,
) -> OutputDecision:
    if not sql_result.ok:
        return OutputDecision(
            allowed=False,
            answer="I could not retrieve that data safely. Please rephrase your question.",
            reason=sql_result.error or "sql_failed",
        )

    cols, rows, block = scrub_rows_for_role(role, sql_result.columns, sql_result.rows)
    if block:
        return OutputDecision(allowed=False, answer=block, reason="pii")

    # Facts-only: refuse if query somehow returned non-company columns that look operational
    if is_facts_only_role(role):
        ops_cols = {
            "cost_usd",
            "prompt_score",
            "input_tokens",
            "output_tokens",
            "ticket_id",
        }
        if any(c.lower() in ops_cols for c in cols):
            return OutputDecision(
                allowed=False,
                answer=(
                    "I can only answer questions about company information like "
                    "clients, services, locations, products, team, and partnerships."
                ),
                reason="scope",
            )

    answer, model_used, token_usage = synthesize_answer(
        role=role,
        original_question=original_question,
        columns=cols,
        rows=rows,
    )
    return OutputDecision(
        allowed=True,
        answer=answer,
        reason="ok",
        model_used=model_used,
        token_usage=token_usage,
    )
