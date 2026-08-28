"""Answer like/dislike feedback — review queue, KB promote, JSONL export."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.auth.deps import AdminUser, AgentUser, CurrentUser
from app.cache.semantic_cache import get_semantic_cache
from app.feedback import store as feedback_store
from app.models.schemas import (
    AnswerFeedbackApplyRequest,
    AnswerFeedbackApplyResponse,
    AnswerFeedbackItem,
    AnswerFeedbackRequest,
)
from app.rag.chroma_store import NearDuplicateError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["feedback"])


def _item(row: dict) -> AnswerFeedbackItem:
    return AnswerFeedbackItem(**row)


@router.post("/feedback", response_model=AnswerFeedbackItem)
def submit_feedback(req: AnswerFeedbackRequest, user: CurrentUser) -> AnswerFeedbackItem:
    email = str(user.get("email") or "")
    try:
        row = feedback_store.create_feedback(
            user_email=email,
            message_id=req.message_id,
            session_id=req.session_id,
            question=req.question,
            answer=req.answer,
            rating=req.rating,
            comment=req.comment,
            corrected_answer=req.corrected_answer,
            department=req.department,
            sources=list(req.sources or []),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if row.get("rating") == "down":
        try:
            get_semantic_cache().clear()
            logger.info(
                "Semantic cache cleared after dislike feedback_id=%s user=%s",
                row.get("id"),
                email,
            )
        except Exception:
            logger.warning("Semantic cache clear after dislike failed", exc_info=True)

    return _item(row)


@router.get("/feedback/mine", response_model=list[AnswerFeedbackItem])
def my_session_feedback(
    user: CurrentUser,
    session_id: str = Query(..., min_length=1),
) -> list[AnswerFeedbackItem]:
    email = str(user.get("email") or "")
    rows = feedback_store.list_feedback_for_session(session_id, email)
    return [_item(r) for r in rows]


@router.get("/feedback/export")
def export_feedback(
    user: AdminUser,
    rating: str | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=20000),
) -> PlainTextResponse:
    try:
        pairs = feedback_store.export_preference_pairs(rating=rating, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    lines = [json.dumps(p, ensure_ascii=False) for p in pairs]
    body = "\n".join(lines) + ("\n" if lines else "")
    return PlainTextResponse(
        content=body,
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": 'attachment; filename="answer_feedback_preferences.jsonl"'
        },
    )


@router.get("/feedback", response_model=list[AnswerFeedbackItem])
def list_feedback(
    user: AgentUser,
    status: str | None = Query(default=None),
    rating: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AnswerFeedbackItem]:
    try:
        rows = feedback_store.list_feedback(
            status=status, rating=rating, limit=limit
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return [_item(r) for r in rows]


@router.post("/feedback/{feedback_id}/apply-kb", response_model=AnswerFeedbackApplyResponse)
def apply_feedback_kb(
    feedback_id: str,
    req: AnswerFeedbackApplyRequest,
    user: AgentUser,
) -> AnswerFeedbackApplyResponse:
    email = str(user.get("email") or "")
    try:
        result = feedback_store.apply_feedback_to_kb(
            feedback_id,
            by_email=email,
            department=req.department,
            answer_override=req.answer,
            title=req.title,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="feedback not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NearDuplicateError as exc:
        match = getattr(exc, "match", {}) or {}
        raise HTTPException(
            status_code=409,
            detail={
                "message": "KB already has a near-duplicate of this answer — not promoted",
                "duplicate_of": match.get("id"),
                "duplicate_title": match.get("title"),
                "duplicate_distance": match.get("distance"),
            },
        ) from exc

    return AnswerFeedbackApplyResponse(
        status="applied",
        kb_doc_id=result["kb_doc_id"],
        feedback=_item(result["feedback"]),
    )


@router.post("/feedback/{feedback_id}/dismiss", response_model=AnswerFeedbackItem)
def dismiss_feedback(feedback_id: str, user: AgentUser) -> AnswerFeedbackItem:
    email = str(user.get("email") or "")
    row = feedback_store.dismiss_feedback(feedback_id, by_email=email)
    if not row:
        raise HTTPException(status_code=404, detail="feedback not found")
    return _item(row)
