"""Query endpoint — normalize, semantic cache, LangGraph pipeline + audit/score."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException

from app.agents.graph import run_pipeline
from app.agents.normalize import normalize_query
from app.agents.scorer import score_prompt
from app.agents.timing import timed
from app.analytics.stats import record_query
from app.audit.cost import costs_for_query
from app.audit.enforcement import apply_enforcement
from app.audit.store import append_event
from app.auth.deps import CurrentUser
from app.cache.semantic_cache import get_semantic_cache
from app.chat.store import CHAT_CONTEXT_LIMIT, ensure_session, load_history, save_message
from app.config import get_settings
from app.models.schemas import QueryRequest, QueryResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["query"])

_RESTRICTED_ANSWER = (
    "Your helpdesk access is temporarily limited until you complete prompt-quality training. "
    "Open the training link from your email (or ask an admin), then click Mark complete. "
    "Training page: /static/training.html"
)


def _latency_ms(node_timings: dict) -> float:
    if not node_timings:
        return 0.0
    return float(sum(float(v or 0) for v in node_timings.values()))


def _resolve_session(req: QueryRequest, user: dict) -> tuple[str, list]:
    """Ensure session exists, return (session_id, prior history for LLM)."""
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
    if score and intent != "restricted":
        apply_enforcement(str(user.get("email") or ""))
    if feedback is not None:
        response.prompt_score = prompt_score
        response.prompt_feedback = feedback


@router.post("/query", response_model=QueryResponse)
def query(req: QueryRequest, user: CurrentUser) -> QueryResponse:
    settings = get_settings()
    timings: dict[str, float] = {}
    t0 = time.perf_counter()

    session_id, prior_history = _resolve_session(req, user)
    has_prior = bool(prior_history)
    _save_user_message(session_id=session_id, user=user, question=req.question)

    # Soft gate — do not run pipeline when restricted
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

    similarity = 0.0
    cached_payload = None
    # Skip semantic cache when the session already has prior turns
    if settings.semantic_cache_enabled and not has_prior:
        sem = get_semantic_cache()
        with timed(timings, "semantic_cache_lookup"):
            cached_payload, similarity = sem.lookup(
                normalized,
                department_hint=req.department_hint,
            )

    if cached_payload:
        logger.info("semantic cache hit similarity=%.3f", similarity)
        with ThreadPoolExecutor(max_workers=1) as pool:
            score_fut = pool.submit(score_prompt, req.question)
            score = score_fut.result()

        cached = dict(cached_payload)
        cached["cached"] = True
        cached["cache_similarity"] = round(similarity, 4)
        node_timings = dict(cached.get("node_timings") or {})
        node_timings.update(timings)
        cached["node_timings"] = node_timings
        cached["session_id"] = session_id
        response = QueryResponse(
            **{k: v for k, v in cached.items() if k in QueryResponse.model_fields}
        )
        response.session_id = session_id
        _append_audit(
            user=user,
            question=req.question,
            response=response,
            score=score,
            intent="helpdesk_query",
            from_cache=True,
        )
        _save_assistant_message(session_id=session_id, user=user, response=response)
        payload = response.model_dump()
        payload["_question"] = req.question
        record_query(payload, cached=True)
        return response

    # Parallel score + pipeline
    with ThreadPoolExecutor(max_workers=2) as pool:
        score_fut = pool.submit(score_prompt, req.question)
        pipe_fut = pool.submit(
            run_pipeline,
            query=req.question,
            normalized_query=normalized,
            department_hint=req.department_hint,
            user_id=user.get("id"),
            user_email=user.get("email"),
            model_preference=req.model_preference,
            session_id=session_id,
            conversation_history=prior_history,
        )
        score = score_fut.result()
        result = pipe_fut.result()

    node_timings = dict(result.get("node_timings") or {})
    node_timings.update(timings)

    response = QueryResponse(
        answer=result.get("answer") or "",
        department=result.get("department") or "unknown",
        severity=result.get("severity") or "routine",
        sources=list(result.get("sources") or []),
        cached=False,
        cache_similarity=round(similarity, 4) if similarity else None,
        model_used=result.get("model_used") or "",
        attempted_depts=list(result.get("attempted_depts") or []),
        retry_count=int(result.get("retry_count") or 0),
        escalated=bool(result.get("escalated")),
        escalation_reason=result.get("escalation_reason"),
        ticket_id=result.get("ticket_id"),
        classify_reason=result.get("classify_reason") or "",
        context_used=bool(result.get("context_used")),
        token_usage=dict(result.get("token_usage") or {}),
        node_timings=node_timings,
        session_id=session_id,
    )

    # Cache only routine + grounded (non-escalated) answers on fresh sessions
    if (
        settings.semantic_cache_enabled
        and not has_prior
        and response.severity == "routine"
        and response.context_used
        and not response.escalated
        and response.sources
        and not response.ticket_id
    ):
        with timed(node_timings, "semantic_cache_write"):
            get_semantic_cache().store(
                normalized,
                response.model_dump(),
                department_hint=req.department_hint,
            )
        response.node_timings = node_timings

    _append_audit(
        user=user,
        question=req.question,
        response=response,
        score=score,
        intent="helpdesk_query",
        from_cache=False,
    )
    _save_assistant_message(session_id=session_id, user=user, response=response)
    payload = response.model_dump()
    payload["_question"] = req.question
    record_query(payload, cached=False)
    return response
