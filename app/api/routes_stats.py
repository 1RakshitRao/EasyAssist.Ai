"""Dashboard analytics endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app.analytics.ops_health import compute_ops_health
from app.analytics.stats import reset_stats, snapshot
from app.auth.deps import AdminUser, AgentUser
from app.cache.semantic_cache import get_semantic_cache
from app.rag.chroma_store import get_store
from app.tickets.store import TICKET_TYPE_ESCALATION, TICKET_TYPE_UNKNOWN, count_open

router = APIRouter(tags=["stats"])


def _stats_payload():
    store = get_store()
    return snapshot(
        open_tickets=count_open(TICKET_TYPE_UNKNOWN),
        open_escalations=count_open(TICKET_TYPE_ESCALATION),
        kb_counts=store.collection_counts(),
    )


@router.get("/stats")
def get_stats(_user: AgentUser):
    return _stats_payload()


@router.get("/stats/ops")
def get_ops_health(_user: AgentUser):
    """Operations Health dashboard — ticket KPIs, trends, and insights."""
    return compute_ops_health()


@router.post("/stats/reset")
def reset_session_stats(_admin: AdminUser, clear_semantic_cache: bool = True):
    """
    Clear in-memory dashboard KPIs / recent queries.
    Optionally also clears the semantic FAQ cache (persisted in Chroma).
    Does not delete KB documents or tickets.
    """
    reset_stats()
    cache_cleared = 0
    if clear_semantic_cache:
        cache = get_semantic_cache()
        before = cache.count()
        cache.clear()
        cache_cleared = before
    return {
        "status": "ok",
        "semantic_cache_cleared": cache_cleared,
        "stats": _stats_payload(),
    }
