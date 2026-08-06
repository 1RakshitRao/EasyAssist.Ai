"""LangGraph nodes for Supervisor routing and non-helpdesk pipelines."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.agents.supervisor import supervise
from app.agents.timing import ensure_timings, timed
from app.config import get_settings
from app.documents.options import is_allowed_operation
from app.llm.client import cached_system, complete, merge_token_usage

logger = logging.getLogger(__name__)

DIRECT_REPLY_SYSTEM = """You are a friendly internal helpdesk AI assistant at Ampcus.
Respond naturally to conversational messages.
Be warm, brief, and professional.
If they seem to have a real question, invite them to ask it.
If they asked about a document but none is uploaded, invite them to upload one in the chat document panel."""

BLOCK_ANSWER = (
    "I can only help with questions about company policies, "
    "your own tasks, and company information. "
    "I'm not able to help with that request."
)

DECLINE_ANSWER = (
    "I'm set up specifically for work-related questions — "
    "HR policies, IT support, compliance, legal, and company information. "
    "Is there something in those areas I can help with?"
)

RESERVATION_STUB_ANSWER = (
    "Guesthouse reservations are coming soon. "
    "You'll be able to check availability and manage bookings from "
    "My Workspace when that module launches."
)


def supervisor_node(state: Dict[str, Any]) -> Dict[str, Any]:
    timings = ensure_timings(state)
    with timed(timings, "supervisor"):
        result = supervise(
            state.get("query") or "",
            user_role=str(state.get("user_role") or "employee"),
            user_email=str(state.get("user_email") or ""),
            has_document=bool(state.get("has_document")),
            joining_date=state.get("joining_date"),
            onboarding_active=bool(state.get("onboarding_active")),
        )
        return {
            "intent": result["intent"],
            "intent_confidence": result.get("confidence") or "medium",
            "intent_reason": result.get("reason") or "",
            "document_operation": result.get("document_operation"),
            "node_timings": timings,
        }


def direct_reply_node(state: Dict[str, Any]) -> Dict[str, Any]:
    timings = ensure_timings(state)
    query = state.get("query") or ""
    with timed(timings, "direct_reply"):
        if not state.get("has_document") and any(
            w in query.lower() for w in ("summarize", "this document", "upload")
        ):
            answer = (
                "I'd be happy to help with your document — please upload a file "
                "using the document panel in chat first, then ask again."
            )
            return {
                "answer": answer,
                "model_used": "none",
                "token_usage": {},
                "node_timings": timings,
            }
        settings = get_settings()
        try:
            result = complete(
                model=settings.classifier_model,
                system=cached_system(DIRECT_REPLY_SYSTEM),
                messages=[{"role": "user", "content": query}],
                max_tokens=200,
            )
            usage = merge_token_usage(state.get("token_usage"), result.token_usage)
            return {
                "answer": (result.text or "").strip() or "Hello! How can I help you today?",
                "model_used": f"{result.provider}:{result.model}",
                "token_usage": usage,
                "node_timings": timings,
            }
        except Exception:
            logger.exception("direct_reply failed")
            return {
                "answer": "Hello! How can I help you with HR, IT, compliance, or legal today?",
                "model_used": "fallback",
                "token_usage": state.get("token_usage") or {},
                "node_timings": timings,
            }


def block_node(state: Dict[str, Any]) -> Dict[str, Any]:
    timings = ensure_timings(state)
    with timed(timings, "block"):
        return {
            "answer": BLOCK_ANSWER,
            "model_used": "none",
            "token_usage": state.get("token_usage") or {},
            "block_kind": "restricted",
            "node_timings": timings,
        }


def decline_node(state: Dict[str, Any]) -> Dict[str, Any]:
    timings = ensure_timings(state)
    with timed(timings, "decline"):
        return {
            "answer": DECLINE_ANSWER,
            "model_used": "none",
            "token_usage": state.get("token_usage") or {},
            "node_timings": timings,
        }


def reservation_node(state: Dict[str, Any]) -> Dict[str, Any]:
    timings = ensure_timings(state)
    with timed(timings, "reservation"):
        from app.reservations.reservation_agent import handle_reservation_query

        result = handle_reservation_query(
            user_email=str(state.get("user_email") or ""),
            query=state.get("query") or "",
            session_id=state.get("session_id"),
        )
        return {
            "answer": result.get("answer") or "",
            "department": result.get("department") or "hr",
            "severity": result.get("severity") or "routine",
            "sources": list(result.get("sources") or []),
            "model_used": result.get("model_used") or "reservation_agent",
            "context_used": bool(result.get("context_used")),
            "token_usage": merge_token_usage(
                state.get("token_usage"), result.get("token_usage") or {}
            ),
            "reservation_calendar": result.get("reservation_calendar"),
            "node_timings": timings,
        }


def semantic_cache_check_node(state: Dict[str, Any]) -> Dict[str, Any]:
    timings = ensure_timings(state)
    settings = get_settings()
    with timed(timings, "semantic_cache_check"):
        if state.get("has_prior") or not settings.semantic_cache_enabled:
            return {"cached": False, "node_timings": timings}

        from app.cache.semantic_cache import get_semantic_cache

        normalized = state.get("normalized_query") or state.get("query") or ""
        sem = get_semantic_cache()
        payload, similarity = sem.lookup(
            normalized,
            department_hint=state.get("department_hint"),
        )
        if not payload:
            return {"cached": False, "cache_similarity": round(similarity, 4), "node_timings": timings}

        answer = payload.get("answer") or ""
        return {
            "answer": answer,
            "department": payload.get("department") or "unknown",
            "severity": payload.get("severity") or "routine",
            "sources": list(payload.get("sources") or []),
            "cached": True,
            "cache_similarity": round(similarity, 4),
            "model_used": payload.get("model_used") or "semantic_cache",
            "attempted_depts": list(payload.get("attempted_depts") or []),
            "retry_count": int(payload.get("retry_count") or 0),
            "escalated": bool(payload.get("escalated")),
            "escalation_reason": payload.get("escalation_reason"),
            "ticket_id": payload.get("ticket_id"),
            "classify_reason": payload.get("classify_reason") or "",
            "context_used": bool(payload.get("context_used")),
            "token_usage": dict(payload.get("token_usage") or {}),
            "node_timings": timings,
        }


def semantic_cache_write_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Store grounded helpdesk answers after answer node (fresh sessions only)."""
    timings = ensure_timings(state)
    settings = get_settings()
    with timed(timings, "semantic_cache_write"):
        if (
            settings.semantic_cache_enabled
            and not state.get("has_prior")
            and state.get("intent") == "helpdesk_query"
            and (state.get("severity") or "routine") == "routine"
            and state.get("context_used")
            and not state.get("escalated")
            and state.get("sources")
            and not state.get("ticket_id")
            and state.get("answer")
        ):
            from app.cache.semantic_cache import get_semantic_cache

            normalized = state.get("normalized_query") or state.get("query") or ""
            payload = {
                "answer": state.get("answer"),
                "department": state.get("department"),
                "severity": state.get("severity"),
                "sources": list(state.get("sources") or []),
                "model_used": state.get("model_used"),
                "attempted_depts": list(state.get("attempted_depts") or []),
                "retry_count": int(state.get("retry_count") or 0),
                "escalated": bool(state.get("escalated")),
                "escalation_reason": state.get("escalation_reason"),
                "ticket_id": state.get("ticket_id"),
                "classify_reason": state.get("classify_reason") or "",
                "context_used": bool(state.get("context_used")),
                "token_usage": dict(state.get("token_usage") or {}),
            }
            get_semantic_cache().store(
                normalized,
                payload,
                department_hint=state.get("department_hint"),
            )
        return {"node_timings": timings}


def onboarding_node(state: Dict[str, Any]) -> Dict[str, Any]:
    timings = ensure_timings(state)
    with timed(timings, "onboarding"):
        from app.onboarding.onboarding_agent import handle_onboarding_query

        result = handle_onboarding_query(
            user_email=str(state.get("user_email") or ""),
            query=state.get("query") or "",
            normalized_query=state.get("normalized_query") or "",
            department_hint=state.get("department_hint"),
            user_id=state.get("user_id"),
            model_preference=state.get("model_preference"),
            session_id=state.get("session_id"),
            conversation_history=list(state.get("conversation_history") or []),
            include_welcome=bool(state.get("include_welcome")),
        )
        node_timings = dict(result.get("node_timings") or {})
        node_timings.update(timings)
        usage = merge_token_usage(state.get("token_usage"), result.get("token_usage") or {})
        return {
            "answer": result.get("answer") or "",
            "department": result.get("department") or "hr",
            "severity": result.get("severity") or "routine",
            "sources": list(result.get("sources") or []),
            "model_used": result.get("model_used") or "onboarding_agent",
            "attempted_depts": list(result.get("attempted_depts") or []),
            "retry_count": int(result.get("retry_count") or 0),
            "escalated": bool(result.get("escalated")),
            "escalation_reason": result.get("escalation_reason"),
            "ticket_id": result.get("ticket_id"),
            "context_used": bool(result.get("context_used")),
            "token_usage": usage,
            "node_timings": node_timings,
        }


def nlp_node(state: Dict[str, Any]) -> Dict[str, Any]:
    timings = ensure_timings(state)
    with timed(timings, "nlp_query"):
        from app.auth.users import get_user_by_id
        from app.nlp_query.orchestrator import run_nlp_query

        user_id = state.get("user_id")
        user = {
            "id": user_id,
            "email": state.get("user_email"),
            "role": state.get("user_role") or "employee",
        }
        if user_id:
            full = get_user_by_id(str(user_id))
            if full:
                user = {
                    "id": full.get("id"),
                    "email": full.get("email"),
                    "role": full.get("role"),
                    "name": full.get("name"),
                }

        result = run_nlp_query(
            state.get("query") or "",
            user,
            session_id=state.get("session_id"),
        )
        usage = merge_token_usage(state.get("token_usage"), result.get("token_usage") or {})
        return {
            "answer": result.get("answer") or "",
            "department": "nlp",
            "severity": "routine",
            "model_used": result.get("model_used") or "nlp_pipeline",
            "nlp_allowed": bool(result.get("allowed")),
            "block_kind": result.get("block_kind"),
            "context_used": bool(result.get("allowed")),
            "token_usage": usage,
            "node_timings": timings,
        }


def document_node(state: Dict[str, Any]) -> Dict[str, Any]:
    timings = ensure_timings(state)
    with timed(timings, "document_op"):
        from app.documents.analysis_agent import analyze_document
        from app.documents.session_store import get_active_document

        email = str(state.get("user_email") or "")
        sid = str(state.get("session_id") or "")
        op = (state.get("document_operation") or "summarize").strip().lower()
        role = str(state.get("user_role") or "employee")

        if op == "push_to_kb":
            return {
                "answer": (
                    "To add this document to the knowledge base, use the "
                    "'Add to KB' action in the document panel."
                ),
                "department": "document",
                "model_used": "none",
                "node_timings": timings,
            }

        if not is_allowed_operation(role, op):
            return {
                "answer": "That document operation is not available for your role.",
                "department": "document",
                "model_used": "none",
                "node_timings": timings,
            }

        doc = get_active_document(sid, email, include_text=True)
        if not doc or not doc.get("text"):
            return {
                "answer": (
                    "No active document found for this session. "
                    "Upload a file in the document panel first."
                ),
                "department": "document",
                "model_used": "none",
                "node_timings": timings,
            }

        question = state.get("query") if op == "ask" else None
        try:
            analysis = analyze_document(
                text=str(doc["text"]),
                operation=op,
                question=question,
                filename=str(doc.get("filename") or ""),
            )
        except ValueError as exc:
            return {
                "answer": str(exc),
                "department": "document",
                "model_used": "none",
                "node_timings": timings,
            }
        except Exception:
            logger.exception("document_node analyze failed")
            return {
                "answer": "Document analysis failed. Please try again.",
                "department": "document",
                "model_used": "none",
                "node_timings": timings,
            }

        usage = merge_token_usage(state.get("token_usage"), analysis.token_usage)
        return {
            "answer": analysis.result,
            "department": "document",
            "model_used": analysis.model_used or "document_pipeline",
            "context_used": True,
            "token_usage": usage,
            "document_id": str(doc.get("doc_id") or ""),
            "node_timings": timings,
        }
