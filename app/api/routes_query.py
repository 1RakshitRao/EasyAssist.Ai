"""Query endpoint — normalize, semantic cache, LangGraph pipeline."""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.agents.graph import run_pipeline
from app.agents.normalize import normalize_query
from app.agents.timing import timed
from app.analytics.stats import record_query
from app.auth.deps import CurrentUser
from app.cache.semantic_cache import get_semantic_cache
from app.config import get_settings
from app.models.schemas import QueryRequest, QueryResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
def query(req: QueryRequest, user: CurrentUser) -> QueryResponse:
    settings = get_settings()
    timings: dict[str, float] = {}
    with timed(timings, "normalize"):
        normalized = normalize_query(req.question)

    similarity = 0.0
    cached_payload = None
    if settings.semantic_cache_enabled:
        sem = get_semantic_cache()
        with timed(timings, "semantic_cache_lookup"):
            cached_payload, similarity = sem.lookup(
                normalized,
                department_hint=req.department_hint,
            )

    if cached_payload:
        logger.info("semantic cache hit similarity=%.3f", similarity)
        cached = dict(cached_payload)
        cached["cached"] = True
        cached["cache_similarity"] = round(similarity, 4)
        node_timings = dict(cached.get("node_timings") or {})
        node_timings.update(timings)
        cached["node_timings"] = node_timings
        response = QueryResponse(**{k: v for k, v in cached.items() if k in QueryResponse.model_fields})
        payload = response.model_dump()
        payload["_question"] = req.question
        record_query(payload, cached=True)
        return response

    result = run_pipeline(
        query=req.question,
        normalized_query=normalized,
        department_hint=req.department_hint,
        user_id=user.get("id"),
        user_email=user.get("email"),
    )
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
    )

    # Cache only routine + grounded (non-escalated) answers
    if (
        settings.semantic_cache_enabled
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

    payload = response.model_dump()
    payload["_question"] = req.question
    record_query(payload, cached=False)
    return response
