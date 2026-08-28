"""Answer agent — grounded generation with Haiku/Sonnet/Opus role routing."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.agents.timing import ensure_timings, timed
from app.audit.query_trace import get_tracer, tracer_from_state
from app.config import get_settings
from app.llm.client import cached_system, complete, merge_token_usage, is_llm_configured, resolve_answer_model

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
    model_preference: str | None = None,
    conversation_history: List[Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    settings = get_settings()
    model = resolve_answer_model(
        severity, escalated=escalated, preference=model_preference
    )

    if not chunks:
        logger.warning("generate_answer called with empty chunks — refusing")
        return {
            "answer": NO_CONTEXT_ANSWER,
            "model_used": "none",
            "token_usage": {},
            "context_used": False,
        }

    if not is_llm_configured():
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

    history: List[Dict[str, str]] = []
    for turn in conversation_history or []:
        role = str((turn or {}).get("role") or "").strip().lower()
        content = str((turn or {}).get("content") or "")
        if role in {"user", "assistant"} and content:
            history.append({"role": role, "content": content})
    messages = history + [{"role": "user", "content": user_msg}]

    tracer = get_tracer()
    try:
        if tracer:
            tracer.llm_called("ANSWER", model, len(user_msg.split()))
        result = complete(
            model=model,
            system=cached_system(ANSWER_SYSTEM),
            messages=messages,
            max_tokens=1024,
        )
        if tracer:
            in_tok = int((result.token_usage or {}).get("input_tokens") or 0)
            out_tok = int((result.token_usage or {}).get("output_tokens") or 0)
            if in_tok:
                tracer.llm_called("ANSWER", f"{result.provider}:{result.model}", in_tok)
            tracer.llm_responded(
                "ANSWER",
                f"{result.provider}:{result.model}",
                out_tok,
                0.0,
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
    tracer = tracer_from_state(state)
    if tracer:
        tracer.agent_started("ANSWER", "Generating grounded answer")
    with timed(timings, "answer"):
        result = generate_answer(
            question=state.get("query") or state.get("normalized_query") or "",
            chunks=list(state.get("chunks") or []),
            severity=state.get("severity") or "routine",
            escalated=bool(state.get("escalated")),
            escalation_reason=state.get("escalation_reason"),
            model_preference=state.get("model_preference"),
            conversation_history=list(state.get("conversation_history") or []),
        )
        usage = merge_token_usage(state.get("token_usage"), result.get("token_usage") or {})
        logger.info(
            "answer model=%s context_used=%s len=%d",
            result.get("model_used"),
            result.get("context_used"),
            len(result.get("answer") or ""),
        )
        if tracer:
            tracer.agent_done(
                "ANSWER",
                f"Answer generated ({len(result.get('answer') or '')} chars)",
                model_used=result.get("model_used"),
            )
        return {
            "answer": result["answer"],
            "model_used": result.get("model_used") or state.get("model_used") or "",
            "token_usage": usage,
            "context_used": bool(result.get("context_used")),
            "node_timings": timings,
        }
