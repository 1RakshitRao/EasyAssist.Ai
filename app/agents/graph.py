"""LangGraph Helpdesk pipeline — agents execute; graph decides."""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal

from langgraph.graph import END, START, StateGraph

from app.agents.answer import answer_node
from app.agents.classifier import classify_node
from app.agents.escalate import escalate_node, should_escalate
from app.agents.retriever import retrieve_node
from app.agents.state import HelpdeskState
from app.agents.ticket import create_ticket_node
from app.config import get_settings

logger = logging.getLogger(__name__)


def route_after_classify(state: HelpdeskState) -> Literal["retrieve"]:
    """Always retrieve — unknown tickets are created only after KB miss."""
    logger.info(
        "route_after_classify -> retrieve (dept=%s)",
        state.get("department"),
    )
    return "retrieve"


def route_after_retrieve(
    state: HelpdeskState,
) -> Literal["classify", "escalate", "answer", "create_ticket"]:
    """Pure routing — no LLM, no I/O."""
    chunks = state.get("chunks") or []
    retry_count = int(state.get("retry_count") or 0)
    max_retries = get_settings().retrieve_max_retries
    department = (state.get("department") or "").lower()
    severity = state.get("severity") or "routine"
    attempted = state.get("attempted_depts") or []

    if not chunks:
        # Full multi-KB search already done (unknown path) or retries exhausted
        if len(attempted) >= 4 or retry_count >= max_retries:
            logger.info("route_after_retrieve -> create_ticket (KB not recognized)")
            return "create_ticket"
        logger.info(
            "route_after_retrieve -> classify (empty, retry_count=%s)",
            retry_count,
        )
        return "classify"

    if should_escalate(department, severity):
        logger.info("route_after_retrieve -> escalate")
        return "escalate"

    logger.info("route_after_retrieve -> answer")
    return "answer"


def build_graph():
    graph = StateGraph(HelpdeskState)
    graph.add_node("classify", classify_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("escalate", escalate_node)
    graph.add_node("answer", answer_node)
    graph.add_node("create_ticket", create_ticket_node)

    graph.add_edge(START, "classify")
    graph.add_edge("classify", "retrieve")
    graph.add_conditional_edges(
        "retrieve",
        route_after_retrieve,
        {
            "classify": "classify",
            "escalate": "escalate",
            "answer": "answer",
            "create_ticket": "create_ticket",
        },
    )
    graph.add_edge("escalate", "answer")
    graph.add_edge("answer", END)
    graph.add_edge("create_ticket", END)
    return graph.compile()


_compiled = None


def get_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled


def reset_graph() -> None:
    """Force recompile (useful in tests)."""
    global _compiled
    _compiled = None


def run_pipeline(
    query: str,
    normalized_query: str,
    department_hint: str | None = None,
    *,
    user_id: str | None = None,
    user_email: str | None = None,
    model_preference: str | None = None,
    session_id: str | None = None,
    conversation_history: list | None = None,
) -> Dict[str, Any]:
    initial: HelpdeskState = {
        "query": query,
        "normalized_query": normalized_query,
        "department_hint": department_hint,
        "attempted_depts": [],
        "retry_count": 0,
        "chunks": [],
        "sources": [],
        "escalated": False,
        "escalation_reason": None,
        "ticket_id": None,
        "cached": False,
        "context_used": False,
        "token_usage": {},
        "node_timings": {},
        "user_id": user_id,
        "user_email": user_email,
        "model_preference": model_preference or "auto",
        "session_id": session_id,
        "conversation_history": list(conversation_history or []),
    }
    graph = get_graph()
    return graph.invoke(initial)
