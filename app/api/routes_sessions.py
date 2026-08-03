"""Chat session CRUD — list, create, load messages, rename, delete."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.auth.deps import CurrentUser
from app.chat.store import (
    delete_session,
    ensure_session,
    get_messages,
    list_sessions,
    new_session_id,
    rename_session,
)
from app.models.schemas import (
    SessionCreateResponse,
    SessionMessage,
    SessionRenameRequest,
    SessionSummary,
)

router = APIRouter(tags=["sessions"])


@router.post("/sessions", response_model=SessionCreateResponse)
def create_session(user: CurrentUser) -> SessionCreateResponse:
    email = str(user.get("email") or "")
    sid = new_session_id()
    ensure_session(sid, email, title_seed="")
    return SessionCreateResponse(session_id=sid)


@router.get("/sessions", response_model=list[SessionSummary])
def get_sessions(user: CurrentUser) -> list[SessionSummary]:
    email = str(user.get("email") or "")
    rows = list_sessions(email)
    return [SessionSummary(**r) for r in rows]


@router.get("/sessions/{session_id}/messages", response_model=list[SessionMessage])
def session_messages(session_id: str, user: CurrentUser) -> list[SessionMessage]:
    email = str(user.get("email") or "")
    rows = get_messages(session_id, email)
    if rows is None:
        raise HTTPException(status_code=404, detail="session not found")
    return [SessionMessage(**r) for r in rows]


@router.patch("/sessions/{session_id}", response_model=SessionSummary)
def patch_session(
    session_id: str, body: SessionRenameRequest, user: CurrentUser
) -> SessionSummary:
    email = str(user.get("email") or "")
    updated = rename_session(session_id, email, body.title)
    if updated is None:
        raise HTTPException(status_code=404, detail="session not found")
    rows = list_sessions(email)
    for row in rows:
        if row["session_id"] == session_id:
            return SessionSummary(**row)
    return SessionSummary(
        session_id=updated["session_id"],
        title=updated["title"],
        created_at=updated["created_at"],
        last_message_at=updated["updated_at"],
        message_count=0,
    )


@router.delete("/sessions/{session_id}")
def remove_session(session_id: str, user: CurrentUser) -> dict:
    email = str(user.get("email") or "")
    ok = delete_session(session_id, email)
    if not ok:
        raise HTTPException(status_code=404, detail="session not found")
    return {"status": "ok", "session_id": session_id}
