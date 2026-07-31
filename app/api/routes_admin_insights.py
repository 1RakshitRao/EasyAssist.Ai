"""Admin insights — durable SQLite cost + score attribution."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from app.audit.enforcement import complete_training
from app.audit.store import list_user_queries, system_summary
from app.auth.deps import AdminUser

router = APIRouter(prefix="/admin", tags=["admin-insights"])


@router.get("/insights")
def admin_insights(_admin: AdminUser) -> Dict[str, Any]:
    return system_summary()


@router.get("/users/{email}/queries")
def admin_user_queries(email: str, _admin: AdminUser, limit: int = 50) -> Dict[str, Any]:
    rows = list_user_queries(email, limit=min(max(limit, 1), 200))
    return {"user_email": email.lower(), "queries": rows}


@router.post("/users/{email}/training-complete")
def admin_training_complete(email: str, _admin: AdminUser) -> Dict[str, Any]:
    row = complete_training(email)
    return {"status": "ok", "user_email": email.lower(), "training": row}
