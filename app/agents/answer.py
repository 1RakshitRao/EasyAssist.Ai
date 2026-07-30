"""Answer agent — grounded generation with Haiku/Sonnet/Opus role routing."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.agents.timing import ensure_timings, timed
from app.config import get_settings
from app.llm.client import cached_system, complete, merge_token_usage, resolve_answer_model

logger = logging.getLogger(__name__)

NO_CONTEXT_ANSWER = (
    "I could not find this in the Ampcus knowledge base. "
    "Please escalate to the appropriate helpdesk team for a human response."
)

ANSWER_SYSTEM = """You are the Ampcus Helpdesk answer assistant.
Answer ONLY using the provided context chunks from company policy documents.
If the context is empty or insufficient, say you do not have that information in the knowledge base
and recommend contacting the helpdesk — do not invent policies, numbers, or procedures.
Be concise and professional. Cite policy titles from context when helpful.
If the query was escalated, acknowledge that a human team has also been notified.
"""


def _format_context(chunks: List[Dict[str, Any]]) -> str:
    if not chunks:
        return "(no context retrieved)"
    parts = []
    for i, chunk in enumerate(chunks, 1):
        title = chunk.get("title") or chunk.get("id") or f"chunk-{i}"
        content = chunk.get("content") or ""
        parts.append(f"[{i}] {title}\n{content}")
    return "\n\n".join(parts)


def generate_answer(
    question: str,
    chunks: List[Dict[str, Any]],
    severity: str = "routine",
    escalated: bool = False,
    escalation_reason: str | None = None,
) -> Dict[str, Any]:
    settings = get_settings()
    model = resolve_answer_model(severity, escalated=escalated)

    if not chunks:
        return {
            "answer": NO_CONTEXT_ANSWER,
            "model_used": "none",
            "token_usage": {},
            "context_used": False,
        }

    if settings.llm_provider.lower() == "anthropic" and not settings.anthropic_api_key:
        first = chunks[0].get("content") or NO_CONTEXT_ANSWER
        return {
            "answer": first[:800],
            "model_used": "offline_excerpt",
            "token_usage": {},
            "context_used": True,
        }

    esc_line = ""
    if escalated:
        esc_line = (
            f"\nEscalation flag: true. Reason: {escalation_reason or 'high severity'}. "
            "Mention that the appropriate team has been notified."
        )

    user_msg = (
        f"Question: {question}\n\nContext:\n{_format_context(chunks)}"
        f"{esc_line}\n\nProvide a grounded answer."
    )

    try:
        result = complete(
            model=model,
            system=cached_system(ANSWER_SYSTEM),
            user_content=user_msg,
            max_tokens=1024,
        )
        return {
            "answer": result.text or NO_CONTEXT_ANSWER,
            "model_used": f"{result.provider}:{result.model}",
            "token_usage": result.token_usage,
            "context_used": True,
        }
    except Exception:
        logger.exception("Answer LLM failure — refusing rather than inventing")
        return {
            "answer": NO_CONTEXT_ANSWER,
            "model_used": model,
            "token_usage": {},
            "context_used": False,
        }


def answer_node(state: Dict[str, Any]) -> Dict[str, Any]:
    timings = ensure_timings(state)
    with timed(timings, "answer"):
        result = generate_answer(
            question=state.get("query") or state.get("normalized_query") or "",
            chunks=list(state.get("chunks") or []),
            severity=state.get("severity") or "routine",
            escalated=bool(state.get("escalated")),
            escalation_reason=state.get("escalation_reason"),
        )
        usage = merge_token_usage(state.get("token_usage"), result.get("token_usage") or {})
        logger.info(
            "answer model=%s context_used=%s len=%d",
            result.get("model_used"),
            result.get("context_used"),
            len(result.get("answer") or ""),
        )
        return {
            "answer": result["answer"],
            "model_used": result.get("model_used") or state.get("model_used") or "",
            "token_usage": usage,
            "context_used": bool(result.get("context_used")),
            "node_timings": timings,
        }
