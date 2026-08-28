"""NLP query orchestrator — Access → SQL → Output."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.audit.cost import costs_for_query
from app.audit.store import append_event
from app.llm.client import merge_token_usage
from app.nlp_query.access_agent import evaluate_access
from app.nlp_query.logs import append_nlp_log
from app.nlp_query.output_agent import review_output
from app.nlp_query.sql_agent import format_sql, run_sql_agent

logger = logging.getLogger(__name__)


def _audit_nlp(
    *,
    user: Dict[str, Any],
    question: str,
    intent: str,
    allowed: bool,
    answer: str,
    department: str | None = "nlp",
    model_used: str | None = None,
    token_usage: Dict[str, int] | None = None,
) -> Dict[str, Any]:
    """Write audit_events row with token/cost attribution. Returns cost summary."""
    model = (model_used or "nlp_pipeline").strip() or "nlp_pipeline"
    costs = costs_for_query(
        model_used=model,
        token_usage=token_usage or {},
        from_cache=False,
        severity="routine",
        escalated=False,
    )
    try:
        append_event(
            {
                "user_id": user.get("id"),
                "user_email": user.get("email"),
                "user_role": user.get("role"),
                "query": question,
                "intent": intent,
                "department": department,
                "severity": "routine",
                "model_used": model,
                "input_tokens": costs["input_tokens"],
                "output_tokens": costs["output_tokens"],
                "cost_usd": costs["cost_usd"],
                "from_cache": False,
                "context_used": allowed,
                "answer_length": len(answer or ""),
                "sources": [],
            }
        )
    except Exception:
        logger.warning("nlp audit append failed", exc_info=True)
    return costs


def _log_admin_trail(
    *,
    user: Dict[str, Any],
    question: str,
    sql_text: str | None,
    answer: str,
    allowed: bool,
    block_kind: str | None = None,
    row_count: int | None = None,
    session_id: str | None = None,
) -> None:
    try:
        append_nlp_log(
            user=user,
            question=question,
            sql_text=sql_text,
            answer=answer,
            allowed=allowed,
            block_kind=block_kind,
            row_count=row_count,
            session_id=session_id,
        )
    except Exception:
        logger.warning("nlp admin log append failed", exc_info=True)


def run_nlp_query(
    question: str,
    user: Dict[str, Any],
    *,
    session_id: str | None = None,
) -> Dict[str, Any]:
    role = str(user.get("role") or "employee")
    access = evaluate_access(question, user)
    if not access.allowed:
        intent = {
            "injection": "nlp_injection",
            "meta": "nlp_meta_block",
            "scope": "nlp_scope_block",
            "empty": "nlp_empty",
        }.get(access.block_kind or "", "nlp_blocked")
        costs = _audit_nlp(
            user=user,
            question=question,
            intent=intent,
            allowed=False,
            answer=access.reason,
            model_used="nlp_blocked",
            token_usage={},
        )
        _log_admin_trail(
            user=user,
            question=question,
            sql_text=None,
            answer=access.reason,
            allowed=False,
            block_kind=access.block_kind,
            session_id=session_id,
        )
        return {
            "answer": access.reason,
            "allowed": False,
            "blocked_reason": access.reason,
            "role": role,
            "block_kind": access.block_kind,
            "cost_usd": costs.get("cost_usd", 0),
            "token_usage": {},
            "model_used": "nlp_blocked",
        }

    sql_result = run_sql_agent(access.rewritten_question, access.allowed_tables)
    from app.audit.query_trace import get_tracer

    if tracer := get_tracer():
        sql_preview = (sql_result.sql or "")[:80]
        tracer.agent_step("NLP", f"SQL generated: {sql_preview}")
        tracer.agent_step("NLP", f"rows={len(sql_result.rows or [])}")
    display_sql = sql_result.sql_formatted or (
        format_sql(sql_result.sql) if sql_result.sql else None
    )
    output = review_output(
        role=access.role,
        original_question=question,
        sql_result=sql_result,
    )
    usage = merge_token_usage(
        sql_result.token_usage or {},
        output.token_usage or {},
    )
    # Prefer the synthesis model for costing when present; else SQL-gen model
    model_used = (
        output.model_used
        or sql_result.model_used
        or "nlp_pipeline"
    )
    if sql_result.model_used and output.model_used and sql_result.model_used != output.model_used:
        # Both stages may have billed; label as pipeline but cost from merged tokens
        model_used = output.model_used

    if not output.allowed:
        costs = _audit_nlp(
            user=user,
            question=question,
            intent="nlp_output_block",
            allowed=False,
            answer=output.answer,
            model_used=model_used,
            token_usage=usage,
        )
        _log_admin_trail(
            user=user,
            question=question,
            sql_text=display_sql,
            answer=output.answer,
            allowed=False,
            block_kind="output",
            row_count=len(sql_result.rows) if sql_result.ok else None,
            session_id=session_id,
        )
        return {
            "answer": output.answer,
            "allowed": False,
            "blocked_reason": output.reason or output.answer,
            "role": role,
            "block_kind": "output",
            "cost_usd": costs.get("cost_usd", 0),
            "token_usage": usage,
            "model_used": model_used,
        }

    costs = _audit_nlp(
        user=user,
        question=question,
        intent="nlp_query",
        allowed=True,
        answer=output.answer,
        model_used=model_used,
        token_usage=usage,
    )
    _log_admin_trail(
        user=user,
        question=question,
        sql_text=display_sql,
        answer=output.answer,
        allowed=True,
        row_count=len(sql_result.rows),
        session_id=session_id,
    )
    return {
        "answer": output.answer,
        "allowed": True,
        "blocked_reason": None,
        "role": role,
        "block_kind": None,
        "row_count": len(sql_result.rows),
        "cost_usd": costs.get("cost_usd", 0),
        "token_usage": usage,
        "model_used": model_used,
    }
