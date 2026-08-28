"""LangGraph Helpdesk pipeline — Supervisor routes; agents execute."""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal

from langgraph.graph import END, START, StateGraph

from app.agents.answer import answer_node
from app.agents.answer_no_context import answer_no_context_node
from app.agents.classifier import classify_node
from app.agents.escalate import escalate_node, should_escalate
from app.agents.retriever import retrieve_node
from app.agents.state import HelpdeskState
from app.agents.supervisor_nodes import (
    block_node,
    decline_node,
    direct_reply_node,
    document_node,
    infrastructure_action_node,
    infrastructure_info_node,
    nlp_node,
    onboarding_node,
    reservation_node,
    security_incident_node,
    semantic_cache_check_node,
    semantic_cache_write_node,
    supervisor_node,
)
from app.agents.ticket_confirm import ticket_confirm_prompt_node
from app.config import get_settings

from app.audit.query_trace import tracer_from_state

logger = logging.getLogger(__name__)

_INTENT_TO_NODE = {
    "conversational": "direct_reply",
    "helpdesk_query": "semantic_cache_check",
    "security_incident": "security_incident",
    "nlp_query": "nlp_query",
    "document_op": "document_op",
    "onboarding_query": "onboarding",
    "reservation_query": "reservation",
    "infrastructure_info": "infrastructure_info",
    "infrastructure_action": "infrastructure_action",
    "restricted": "block",
    "out_of_scope": "decline",
}


def resolve_node_for_intent(intent: str) -> str:
    return _INTENT_TO_NODE.get((intent or "helpdesk_query").lower(), "semantic_cache_check")


def route_after_supervisor(
    state: HelpdeskState,
) -> Literal[
    "direct_reply",
    "semantic_cache_check",
    "nlp_query",
    "document_op",
    "onboarding",
    "reservation",
    "infrastructure_info",
    "infrastructure_action",
    "security_incident",
    "block",
    "decline",
]:
    intent = (state.get("intent") or "helpdesk_query").lower()
    node = _INTENT_TO_NODE.get(intent, "semantic_cache_check")
    tracer = tracer_from_state(state)
    if tracer:
        tracer.supervisor_routed(node)
    logger.info("route_after_supervisor intent=%s -> %s", intent, node)
    return node  # type: ignore[return-value]


def route_after_semantic_cache(
    state: HelpdeskState,
) -> Literal["classify", "cache_hit_end"]:
    tracer = tracer_from_state(state)
    if state.get("cached") and state.get("answer"):
        if tracer:
            tracer.agent_done("CACHE", "Returning cached answer")
        logger.info("route_after_semantic_cache -> cache_hit_end")
        return "cache_hit_end"
    if tracer:
        tracer.agent_step("CACHE", "Routing to classify")
    logger.info("route_after_semantic_cache -> classify")
    return "classify"


def route_after_classify(state: HelpdeskState) -> Literal["retrieve"]:
    tracer = tracer_from_state(state)
    dept = state.get("department")
    if tracer:
        tracer.agent_step("CLASSIFIER", f"Routing to retrieve (dept={dept})")
    logger.info(
        "route_after_classify -> retrieve (dept=%s)",
        dept,
    )
    return "retrieve"


def route_after_retrieve(
    state: HelpdeskState,
) -> Literal["classify", "escalate", "answer", "answer_no_context"]:
    chunks = state.get("chunks") or []
    retry_count = int(state.get("retry_count") or 0)
    max_retries = get_settings().retrieve_max_retries
    department = (state.get("department") or "").lower()
    severity = state.get("severity") or "routine"
    attempted = state.get("attempted_depts") or []

    if not chunks:
        if len(attempted) >= 4 or retry_count >= max_retries:
            if tracer := tracer_from_state(state):
                tracer.agent_step("RETRIEVER", "KB miss — answer_no_context")
            logger.info("route_after_retrieve -> answer_no_context (KB not recognized)")
            return "answer_no_context"
        if tracer := tracer_from_state(state):
            tracer.agent_step(
                "RETRIEVER",
                f"Empty retrieval — reclassify (retry_count={retry_count})",
            )
        logger.info(
            "route_after_retrieve -> classify (empty, retry_count=%s)",
            retry_count,
        )
        return "classify"

    if should_escalate(department, severity):
        if tracer := tracer_from_state(state):
            tracer.agent_step("RETRIEVER", "High severity — escalate")
        logger.info("route_after_retrieve -> escalate")
        return "escalate"

    if tracer := tracer_from_state(state):
        tracer.agent_step("RETRIEVER", "Chunks found — answer")
    logger.info("route_after_retrieve -> answer")
    return "answer"


def build_graph():
    graph = StateGraph(HelpdeskState)

    graph.add_node("supervisor", supervisor_node)
    graph.add_node("direct_reply", direct_reply_node)
    graph.add_node("semantic_cache_check", semantic_cache_check_node)
    graph.add_node("classify", classify_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("escalate", escalate_node)
    graph.add_node("answer", answer_node)
    graph.add_node("answer_no_context", answer_no_context_node)
    graph.add_node("ticket_confirm_prompt", ticket_confirm_prompt_node)
    graph.add_node("semantic_cache_write", semantic_cache_write_node)
    graph.add_node("nlp_query", nlp_node)
    graph.add_node("document_op", document_node)
    graph.add_node("onboarding", onboarding_node)
    graph.add_node("reservation", reservation_node)
    graph.add_node("infrastructure_info", infrastructure_info_node)
    graph.add_node("infrastructure_action", infrastructure_action_node)
    graph.add_node("security_incident", security_incident_node)
    graph.add_node("block", block_node)
    graph.add_node("decline", decline_node)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route_after_supervisor,
        {
            "direct_reply": "direct_reply",
            "semantic_cache_check": "semantic_cache_check",
            "nlp_query": "nlp_query",
            "document_op": "document_op",
            "onboarding": "onboarding",
            "reservation": "reservation",
            "infrastructure_info": "infrastructure_info",
            "infrastructure_action": "infrastructure_action",
            "security_incident": "security_incident",
            "block": "block",
            "decline": "decline",
        },
    )

    graph.add_conditional_edges(
        "semantic_cache_check",
        route_after_semantic_cache,
        {
            "classify": "classify",
            "cache_hit_end": END,
        },
    )

    graph.add_edge("classify", "retrieve")
    graph.add_conditional_edges(
        "retrieve",
        route_after_retrieve,
        {
            "classify": "classify",
            "escalate": "escalate",
            "answer": "answer",
            "answer_no_context": "answer_no_context",
        },
    )
    graph.add_edge("escalate", "answer")
    graph.add_edge("answer", "ticket_confirm_prompt")
    graph.add_edge("ticket_confirm_prompt", "semantic_cache_write")
    graph.add_edge("semantic_cache_write", END)
    graph.add_edge("answer_no_context", END)

    for terminal in (
        "direct_reply",
        "nlp_query",
        "document_op",
        "onboarding",
        "reservation",
        "infrastructure_info",
        "infrastructure_action",
        "security_incident",
        "block",
        "decline",
    ):
        graph.add_edge(terminal, END)

    return graph.compile()


_compiled = None


def get_graph():
    global _compiled
    if _compiled is None:
        _compiled = build_graph()
    return _compiled


def reset_graph() -> None:
    global _compiled
    _compiled = None


def run_pipeline(
    query: str,
    normalized_query: str,
    department_hint: str | None = None,
    *,
    user_id: str | None = None,
    user_email: str | None = None,
    user_role: str = "employee",
    model_preference: str | None = None,
    session_id: str | None = None,
    conversation_history: list | None = None,
    joining_date: str | None = None,
    document_id: str | None = None,
    has_document: bool = False,
    onboarding_active: bool = False,
    has_prior: bool = False,
    include_welcome: bool = False,
    tracer: Any = None,
) -> Dict[str, Any]:
    from app.audit.query_trace import QueryTracer, set_tracer

    if isinstance(tracer, QueryTracer):
        set_tracer(tracer)

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
        "user_role": user_role,
        "model_preference": model_preference or "auto",
        "session_id": session_id,
        "conversation_history": list(conversation_history or []),
        "joining_date": joining_date,
        "document_id": document_id,
        "has_document": has_document,
        "onboarding_active": onboarding_active,
        "has_prior": has_prior,
        "include_welcome": include_welcome,
        "intent": "",
        "intent_confidence": "",
        "intent_reason": "",
        "document_operation": None,
        "pending_ticket_confirmation": False,
        "pending_ticket_payload": None,
        "kb_miss_query": None,
        "reservation_calendar": None,
        "onboarding_checklist": None,
        "tracer": tracer,
    }
    graph = get_graph()
    try:
        result = graph.invoke(initial)
    finally:
        if isinstance(tracer, QueryTracer):
            set_tracer(None)
    if not result.get("intent"):
        result["intent"] = "helpdesk_query"
    return result
