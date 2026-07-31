"""In-app notification APIs for agents/admins."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth.deps import AgentUser
from app.tickets.inbox import (
    list_notifications,
    mark_all_read,
    mark_read,
    unread_count,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationResponse(BaseModel):
    id: str
    kind: str = "ticket_created"
    title: str
    body: str
    ticket_id: Optional[str] = None
    ticket_type: Optional[str] = None
    severity: Optional[str] = None
    department: Optional[str] = None
    created_by_email: Optional[str] = None
    created_at: str
    read_at: Optional[str] = None


class UnreadCountResponse(BaseModel):
    unread: int = 0


class MarkAllReadResponse(BaseModel):
    marked: int = Field(0, description="How many notifications were marked read")


@router.get("", response_model=List[NotificationResponse])
def get_notifications(
    _user: AgentUser,
    unread_only: bool = Query(default=False),
    limit: int = Query(default=40, ge=1, le=200),
):
    return [
        NotificationResponse(**n)
        for n in list_notifications(unread_only=unread_only, limit=limit)
    ]


@router.get("/unread-count", response_model=UnreadCountResponse)
def get_unread_count(_user: AgentUser):
    return UnreadCountResponse(unread=unread_count())


@router.post("/{notification_id}/read", response_model=NotificationResponse)
def read_notification(notification_id: str, _user: AgentUser):
    note = mark_read(notification_id)
    if not note:
        raise HTTPException(status_code=404, detail="Notification not found")
    return NotificationResponse(**note)


@router.post("/read-all", response_model=MarkAllReadResponse)
def read_all_notifications(_user: AgentUser):
    return MarkAllReadResponse(marked=mark_all_read())
