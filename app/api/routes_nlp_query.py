"""NLP analytics query + company facts admin API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.auth.deps import AdminUser, CurrentUser
from app.chat.store import ensure_session, save_message
from app.models.schemas import (
    CompanyFactCreate,
    CompanyFactOut,
    NlpQueryRequest,
    NlpQueryResponse,
)
from app.nlp_query.company_facts import create_fact, delete_fact, list_facts
from app.nlp_query.logs import list_nlp_logs
from app.nlp_query.orchestrator import run_nlp_query

logger = logging.getLogger(__name__)
router = APIRouter(tags=["nlp-query"])


@router.post("/nlp-query", response_model=NlpQueryResponse)
def nlp_query(req: NlpQueryRequest, user: CurrentUser) -> NlpQueryResponse:
    """Deprecated for chat UI — use POST /query (Supervisor routes nlp_query)."""
    email = str(user.get("email") or "")
    session_id = None
    if email:
        try:
            session_id = ensure_session(req.session_id, email, title_seed=req.question)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    result = run_nlp_query(req.question, user, session_id=session_id)
    answer = result.get("answer") or ""
    cost_usd = float(result.get("cost_usd") or 0)

    if session_id and email:
        try:
            save_message(
                session_id=session_id,
                user_email=email,
                role="user",
                content=req.question,
                department="nlp",
            )
            save_message(
                session_id=session_id,
                user_email=email,
                role="assistant",
                content=answer,
                department="nlp",
                cost_usd=cost_usd,
            )
        except Exception:
            logger.exception("nlp chat persist failed session=%s", session_id)

    return NlpQueryResponse(
        answer=answer,
        allowed=bool(result.get("allowed")),
        blocked_reason=result.get("blocked_reason"),
        role=str(result.get("role") or user.get("role") or ""),
        block_kind=result.get("block_kind"),
        sql=None,
        sql_raw=None,
        row_count=result.get("row_count"),
        session_id=session_id,
        model_used=result.get("model_used"),
        token_usage=dict(result.get("token_usage") or {}),
        cost_usd=cost_usd,
    )


@router.get("/admin/nlp-logs")
def get_nlp_logs(user: AdminUser, limit: int = 100) -> dict:
    rows = list_nlp_logs(limit=limit)
    return {"count": len(rows), "logs": rows}


@router.get("/admin/company-facts", response_model=list[CompanyFactOut])
def get_company_facts(
    user: AdminUser,
    category: str | None = None,
) -> list[CompanyFactOut]:
    rows = list_facts(category=category, active_only=False)
    return [CompanyFactOut(**r) for r in rows]


@router.post("/admin/company-facts", response_model=CompanyFactOut)
def post_company_fact(body: CompanyFactCreate, user: AdminUser) -> CompanyFactOut:
    try:
        row = create_fact(
            category=body.category,
            name=body.name,
            description=body.description,
            detail_1=body.detail_1,
            detail_2=body.detail_2,
            active=body.active,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return CompanyFactOut(**row)


@router.delete("/admin/company-facts/{fact_id}")
def remove_company_fact(fact_id: str, user: AdminUser) -> dict:
    ok = delete_fact(fact_id)
    if not ok:
        raise HTTPException(status_code=404, detail="fact not found")
    return {"status": "ok", "id": fact_id}
