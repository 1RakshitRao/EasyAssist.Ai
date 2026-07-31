"""Admin ticket APIs — unknown + escalation HITL review."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.auth.deps import AgentUser
from app.models.schemas import (
    TicketAssignRequest,
    TicketPromoteRequest,
    TicketResolveRequest,
    TicketResponse,
)
from app.rag.chroma_store import DEPARTMENTS, NearDuplicateError, get_store
from app.tickets.notify import notify_ticket_resolved
from app.tickets.store import get_ticket, list_tickets, update_ticket

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _to_response(ticket: dict) -> TicketResponse:
    ticket = dict(ticket)
    ticket.setdefault("ticket_type", "unknown")
    ticket.setdefault("severity", "routine")
    ticket.setdefault("created_by_user_id", None)
    ticket.setdefault("created_by_email", None)
    ticket.setdefault("updated_by_user_id", None)
    ticket.setdefault("updated_by_email", None)
    return TicketResponse(**ticket)


@router.get("", response_model=List[TicketResponse])
def get_tickets(
    _user: AgentUser,
    status: Optional[str] = Query(default=None),
    ticket_type: Optional[str] = Query(
        default=None, description="unknown | escalation"
    ),
) -> List[TicketResponse]:
    return [
        _to_response(t)
        for t in list_tickets(status=status, ticket_type=ticket_type)
    ]


@router.get("/{ticket_id}", response_model=TicketResponse)
def get_ticket_by_id(ticket_id: str, _user: AgentUser) -> TicketResponse:
    ticket = get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="ticket not found")
    return _to_response(ticket)


@router.patch("/{ticket_id}/assign", response_model=TicketResponse)
def assign_ticket(
    ticket_id: str, req: TicketAssignRequest, user: AgentUser
) -> TicketResponse:
    dept = req.department.lower().strip()
    if dept not in DEPARTMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"department must be one of: {', '.join(DEPARTMENTS)}",
        )
    ticket = get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="ticket not found")
    if ticket.get("status") == "resolved":
        raise HTTPException(status_code=400, detail="ticket already resolved")

    updated = update_ticket(
        ticket_id,
        assigned_department=dept,
        department=dept,
        status="assigned",
        admin_notes=req.admin_notes,
        updated_by_user_id=user.get("id"),
        updated_by_email=user.get("email"),
    )
    assert updated is not None
    return _to_response(updated)


@router.patch("/{ticket_id}/resolve", response_model=TicketResponse)
def resolve_ticket(
    ticket_id: str, req: TicketResolveRequest, user: AgentUser
) -> TicketResponse:
    """Mark an escalation (or unknown) ticket reviewed/resolved without KB promote."""
    ticket = get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="ticket not found")
    status = (req.status or "resolved").lower().strip()
    if status not in {"resolved", "assigned"}:
        raise HTTPException(status_code=400, detail="status must be resolved or assigned")
    fields: dict = {
        "status": status,
        "admin_notes": req.admin_notes or ticket.get("admin_notes"),
        "updated_by_user_id": user.get("id"),
        "updated_by_email": user.get("email"),
    }
    if status == "resolved" and not ticket.get("resolved_at"):
        from datetime import datetime, timezone

        fields["resolved_at"] = datetime.now(timezone.utc).isoformat()
    updated = update_ticket(ticket_id, **fields)
    assert updated is not None
    if status == "resolved":
        try:
            updated = (
                notify_ticket_resolved(
                    updated,
                    solution=req.admin_notes or updated.get("admin_notes"),
                )
                or updated
            )
        except Exception:
            pass
    return _to_response(updated)


@router.post("/{ticket_id}/promote", response_model=TicketResponse)
def promote_ticket_to_kb(
    ticket_id: str, req: TicketPromoteRequest, user: AgentUser
) -> TicketResponse:
    """Admin labels department (if needed) and stores Q&A into that department KB."""
    ticket = get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail="ticket not found")
    if ticket.get("status") == "resolved" and ticket.get("kb_doc_id"):
        raise HTTPException(status_code=400, detail="ticket already promoted to KB")

    dept = (
        req.department
        or ticket.get("assigned_department")
        or ticket.get("department")
        or ""
    ).lower().strip()
    if dept not in DEPARTMENTS:
        raise HTTPException(
            status_code=400,
            detail="Set department on the request or assign the ticket first",
        )

    title = req.title or f"FAQ: {ticket['question'][:80]}"
    answer_text = (req.answer or req.content or "").strip()
    if not answer_text:
        raise HTTPException(
            status_code=400,
            detail="Provide answer (or content) — the canonical KB text for this question",
        )
    body = f"Question: {ticket['question']}\n\nAnswer: {answer_text}"

    store = get_store()
    try:
        ids = store.add_documents(
            dept,
            [
                {
                    "title": title,
                    "content": body,
                    "metadata": {
                        "source": "hitl_ticket",
                        "ticket_id": ticket_id,
                        "ticket_type": ticket.get("ticket_type", "unknown"),
                    },
                }
            ],
            check_duplicates=True,
        )
    except NearDuplicateError as exc:
        match = exc.match
        raise HTTPException(
            status_code=409,
            detail={
                "message": "KB already has a near-duplicate of this answer — not promoted",
                "department": dept,
                "duplicate_of": match.get("id"),
                "duplicate_title": match.get("title"),
                "duplicate_distance": match.get("distance"),
                "reason": match.get("reason"),
            },
        ) from exc
    from datetime import datetime, timezone

    resolved_at = ticket.get("resolved_at") or datetime.now(timezone.utc).isoformat()
    updated = update_ticket(
        ticket_id,
        assigned_department=dept,
        department=dept,
        status="resolved",
        resolved_at=resolved_at,
        kb_doc_id=ids[0],
        admin_notes=req.admin_notes or ticket.get("admin_notes"),
        updated_by_user_id=user.get("id"),
        updated_by_email=user.get("email"),
    )
    assert updated is not None
    try:
        solution = (
            req.answer
            or req.content
            or req.admin_notes
            or updated.get("admin_notes")
            or ""
        )
        updated = notify_ticket_resolved(updated, solution=solution) or updated
    except Exception:
        pass
    return _to_response(updated)
