"""Infrastructure informational queries — IT KB retrieval."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.agents.answer import answer_node
from app.agents.answer_no_context import answer_no_context_node
from app.agents.classifier import classify_node
from app.agents.retriever import retrieve_node
from app.config import get_settings

logger = logging.getLogger(__name__)


def run_infrastructure_info_query(
    *,
    query: str,
    normalized_query: str,
    user_email: str,
    user_role: str = "employee",
    model_preference: str | None = None,
    session_id: str | None = None,
    conversation_history: List[Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    """IT-scoped KB retrieval for office infrastructure questions."""
    state: Dict[str, Any] = {
        "query": query,
        "normalized_query": normalized_query or query,
        "department_hint": "it",
        "department": "it",
        "severity": "routine",
        "attempted_depts": [],
        "retry_count": 0,
        "chunks": [],
        "sources": [],
        "user_email": user_email,
        "user_role": user_role,
        "model_preference": model_preference or "auto",
        "session_id": session_id,
        "conversation_history": list(conversation_history or []),
        "intent": "infrastructure_info",
        "token_usage": {},
        "node_timings": {},
        "escalated": False,
    }

    state.update(classify_node(state))
    # Force IT department for infrastructure info
    state["department"] = "it"
    state.update(retrieve_node(state))

    chunks = state.get("chunks") or []
    settings = get_settings()
    if not chunks and int(state.get("retry_count") or 0) < settings.retrieve_max_retries:
        state["retry_count"] = settings.retrieve_max_retries

    if chunks:
        state.update(answer_node(state))
    else:
        state.update(answer_no_context_node(state))

    return {
        "answer": state.get("answer") or "",
        "department": "it",
        "severity": state.get("severity") or "routine",
        "sources": list(state.get("sources") or []),
        "model_used": state.get("model_used") or "infrastructure_info",
        "context_used": bool(state.get("context_used")),
        "token_usage": dict(state.get("token_usage") or {}),
        "node_timings": dict(state.get("node_timings") or {}),
        "pending_ticket_confirmation": bool(state.get("pending_ticket_confirmation")),
        "pending_ticket_payload": state.get("pending_ticket_payload"),
    }
