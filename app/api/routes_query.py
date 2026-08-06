"""Query endpoint — Supervisor-routed unified chat pipeline + audit/score."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Tuple

from fastapi import APIRouter, HTTPException

from app.agents.graph import run_pipeline
from app.agents.normalize import normalize_query
from app.agents.scorer import score_prompt
from app.agents.timing import timed
from app.agents.ticket import (
    TICKET_CONFIRMED_ANSWER,
    create_ticket_from_payload,
    decline_ticket_message,
)
from app.analytics.stats import record_query
from app.audit.cost import costs_for_query
from app.audit.enforcement import apply_enforcement
from app.audit.store import append_event
from app.auth.deps import CurrentUser
from app.chat.pending_ticket import clear_pending, get_pending, save_pending
from app.chat.store import CHAT_CONTEXT_LIMIT, ensure_session, load_history, save_message
from app.documents.session_store import get_active_document
from app.onboarding import store as onboarding_store
from app.tickets.store import TICKET_TYPE_ESCALATION, TICKET_TYPE_UNKNOWN

from app.models.schemas import QueryRequest, QueryResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["query"])

_RESTRICTED_ANSWER = (
    "Your helpdesk access is temporarily limited until you complete prompt-quality training. "
    "Open the training link from your email (or ask an admin), then click Mark complete. "
    "Training page: /static/training.html"
)

_CONFIRM_LABELS = {True: "Yes, open ticket", False: "No thanks"}


def _latency_ms(node_timings: dict) -> float:
    if not node_timings:
        return 0.0
    return float(sum(float(v or 0) for v in node_timings.values()))


def _onboarding_context_for_user(user_email: str) -> Tuple[bool, Optional[str]]:
    """True if user has an active, incomplete onboarding profile."""
    emp = onboarding_store.get_employee(user_email)
    if not emp or emp.get("onboarding_complete") or not emp.get("active", True):
        return False, None
    return True, emp.get("joining_date")


def _resolve_session(req: QueryRequest, user: dict) -> tuple[str, list]:
    email = str(user.get("email") or "")
    try:
        session_id = ensure_session(req.session_id, email, title_seed=req.question)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    history = load_history(session_id, email, limit=CHAT_CONTEXT_LIMIT)
    return session_id, history


def _save_user_message(*, session_id: str, user: dict, question: str) -> None:
    email = str(user.get("email") or "")
    try:
        save_message(
            session_id=session_id,
            user_email=email,
            role="user",
            content=question,
        )
    except PermissionError as exc:
        logger.warning("chat user persist failed: %s", exc)
    except Exception:
        logger.exception("chat user persist failed session=%s", session_id)


def _save_assistant_message(
    *,
    session_id: str,
    user: dict,
    response: QueryResponse,
) -> None:
    email = str(user.get("email") or "")
    try:
        costs = costs_for_query(
            model_used=response.model_used,
            token_usage=response.token_usage,
            from_cache=bool(response.cached),
            severity=response.severity,
            escalated=response.escalated,
        )
        save_message(
            session_id=session_id,
            user_email=email,
            role="assistant",
            content=response.answer or "",
            department=response.department,
            cost_usd=float(costs.get("cost_usd") or 0),
        )
    except PermissionError as exc:
        logger.warning("chat assistant persist failed: %s", exc)
    except Exception:
        logger.exception("chat assistant persist failed session=%s", session_id)


def _append_audit(
    *,
    user: dict,
    question: str,
    response: QueryResponse,
    score: dict | None,
    intent: str,
    from_cache: bool,
) -> None:
    costs = costs_for_query(
        model_used=response.model_used,
        token_usage=response.token_usage,
        from_cache=from_cache,
        severity=response.severity,
        escalated=response.escalated,
    )
    feedback = None
    prompt_score = None
    issues = []
    improved = None
    if score:
        prompt_score = score.get("score")
        issues = score.get("issues") or []
        improved = score.get("improved_query")
        feedback = {
            "issues": issues,
            "improved_query": improved,
            "reason": score.get("reason"),
        }

    append_event(
        {
            "user_id": user.get("id"),
            "user_email": user.get("email"),
            "user_role": user.get("role"),
            "query": question,
            "intent": intent,
            "department": response.department,
            "severity": response.severity,
            "model_used": response.model_used,
            "input_tokens": costs["input_tokens"],
            "output_tokens": costs["output_tokens"],
            "cost_usd": costs["cost_usd"],
            "from_cache": from_cache,
            "context_used": response.context_used,
            "prompt_score": prompt_score,
            "score_issues": issues,
            "improved_query": improved,
            "latency_ms": _latency_ms(response.node_timings or {}),
            "answer_length": len(response.answer or ""),
            "sources": list(response.sources or []),
            "ticket_id": response.ticket_id,
        }
    )
    logger.info(
        "query complete intent=%s confidence=%s dept=%s severity=%s cached=%s "
        "sim=%s escalated=%s ticket=%s model=%s user=%s pending=%s",
        intent,
        response.intent_confidence or "—",
        response.department,
        response.severity,
        from_cache,
        response.cache_similarity,
        response.escalated,
        response.ticket_id or "—",
        response.model_used,
        user.get("email"),
        response.pending_ticket_confirmation,
    )
    if score and intent not in ("restricted", "block"):
        apply_enforcement(str(user.get("email") or ""))
    if feedback is not None:
        response.prompt_score = prompt_score
        response.prompt_feedback = feedback


def _result_to_response(result: dict, session_id: str) -> QueryResponse:
    return QueryResponse(
        answer=result.get("answer") or "",
        department=result.get("department") or "unknown",
        severity=result.get("severity") or "routine",
        sources=list(result.get("sources") or []),
        cached=bool(result.get("cached")),
        cache_similarity=result.get("cache_similarity"),
        model_used=result.get("model_used") or "",
        attempted_depts=list(result.get("attempted_depts") or []),
        retry_count=int(result.get("retry_count") or 0),
        escalated=bool(result.get("escalated")),
        escalation_reason=result.get("escalation_reason"),
        ticket_id=result.get("ticket_id"),
        classify_reason=result.get("classify_reason") or result.get("intent_reason") or "",
        context_used=bool(result.get("context_used")),
        token_usage=dict(result.get("token_usage") or {}),
        node_timings=dict(result.get("node_timings") or {}),
        session_id=session_id,
        intent=result.get("intent") or "helpdesk_query",
        intent_confidence=result.get("intent_confidence"),
        nlp_allowed=result.get("nlp_allowed"),
        block_kind=result.get("block_kind"),
        pending_ticket_confirmation=bool(result.get("pending_ticket_confirmation")),
        reservation_calendar=result.get("reservation_calendar"),
    )


def _handle_ticket_confirmation(
    *,
    req: QueryRequest,
    user: dict,
    session_id: str,
    pending: dict,
    t0: float,
) -> QueryResponse:
    label = _CONFIRM_LABELS.get(req.confirm_ticket, "(confirm)")
    _save_user_message(session_id=session_id, user=user, question=label)

    if req.confirm_ticket is True:
        ticket = create_ticket_from_payload(
            pending,
            user_id=user.get("id"),
            user_email=user.get("email"),
        )
        clear_pending(session_id)
        ticket_type = pending.get("ticket_type") or TICKET_TYPE_UNKNOWN
        response = QueryResponse(
            answer=TICKET_CONFIRMED_ANSWER,
            department=pending.get("department") or "unknown",
            severity=pending.get("severity") or "routine",
            model_used="hitl_ticket",
            ticket_id=ticket["id"],
            escalated=ticket_type == TICKET_TYPE_ESCALATION,
            context_used=False,
            classify_reason=pending.get("reason") or "",
            node_timings={"confirm": round((time.perf_counter() - t0) * 1000, 2)},
            session_id=session_id,
            intent="helpdesk_query",
            pending_ticket_confirmation=False,
        )
        audit_q = pending.get("question") or req.question
    else:
        clear_pending(session_id)
        dept = pending.get("department") or "unknown"
        response = QueryResponse(
            answer=decline_ticket_message(dept),
            department=dept,
            severity=pending.get("severity") or "routine",
            model_used="none",
            context_used=False,
            node_timings={"decline": round((time.perf_counter() - t0) * 1000, 2)},
            session_id=session_id,
            intent="helpdesk_query",
            pending_ticket_confirmation=False,
        )
        audit_q = pending.get("question") or req.question

    _append_audit(
        user=user,
        question=audit_q,
        response=response,
        score=None,
        intent="helpdesk_query",
        from_cache=False,
    )
    _save_assistant_message(session_id=session_id, user=user, response=response)
    payload = response.model_dump()
    payload["_question"] = audit_q
    record_query(payload, cached=False)
    return response


@router.post("/query", response_model=QueryResponse)
def query(req: QueryRequest, user: CurrentUser) -> QueryResponse:
    timings: dict[str, float] = {}
    t0 = time.perf_counter()

    session_id, prior_history = _resolve_session(req, user)
    has_prior = bool(prior_history)
    pending = get_pending(session_id)

    if req.confirm_ticket is not None:
        if not pending:
            raise HTTPException(
                status_code=400,
                detail="No pending ticket confirmation for this session.",
            )
        return _handle_ticket_confirmation(
            req=req,
            user=user,
            session_id=session_id,
            pending=pending,
            t0=t0,
        )

    if pending:
        clear_pending(session_id)

    _save_user_message(session_id=session_id, user=user, question=req.question)

    if user.get("access_restricted"):
        response = QueryResponse(
            answer=_RESTRICTED_ANSWER,
            department="unknown",
            severity="routine",
            sources=[],
            cached=False,
            model_used="training_gate",
            classify_reason="access_restricted",
            context_used=False,
            node_timings={"gate": round((time.perf_counter() - t0) * 1000, 2)},
            session_id=session_id,
            intent="restricted",
        )
        _append_audit(
            user=user,
            question=req.question,
            response=response,
            score=None,
            intent="restricted",
            from_cache=False,
        )
        _save_assistant_message(session_id=session_id, user=user, response=response)
        payload = response.model_dump()
        payload["_question"] = req.question
        record_query(payload, cached=False)
        return response

    with timed(timings, "normalize"):
        normalized = normalize_query(req.question)

    user_email = str(user.get("email") or "")
    onboarding_active, joining_date = _onboarding_context_for_user(user_email)
    active_doc = get_active_document(session_id, user_email, include_text=False)
    has_document = active_doc is not None
    document_id = str(active_doc["doc_id"]) if active_doc else None

    with ThreadPoolExecutor(max_workers=2) as pool:
        score_fut = pool.submit(score_prompt, req.question)
        pipe_fut = pool.submit(
            run_pipeline,
            query=req.question,
            normalized_query=normalized,
            department_hint=req.department_hint,
            user_id=user.get("id"),
            user_email=user_email,
            user_role=str(user.get("role") or "employee"),
            model_preference=req.model_preference,
            session_id=session_id,
            conversation_history=prior_history,
            joining_date=joining_date,
            document_id=document_id,
            has_document=has_document,
            onboarding_active=onboarding_active,
            has_prior=has_prior,
            include_welcome=not has_prior,
        )
        score = score_fut.result()
        result = pipe_fut.result()

    node_timings = dict(result.get("node_timings") or {})
    node_timings.update(timings)
    result["node_timings"] = node_timings

    if result.get("pending_ticket_confirmation") and result.get("pending_ticket_payload"):
        save_pending(session_id, result["pending_ticket_payload"])

    response = _result_to_response(result, session_id)
    audit_intent = response.intent or "helpdesk_query"

    _append_audit(
        user=user,
        question=req.question,
        response=response,
        score=score,
        intent=audit_intent,
        from_cache=bool(response.cached),
    )
    _save_assistant_message(session_id=session_id, user=user, response=response)
    payload = response.model_dump()
    payload["_question"] = req.question
    record_query(payload, cached=bool(response.cached))
    return response
