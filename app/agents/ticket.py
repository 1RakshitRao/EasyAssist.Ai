"""HITL ticket helpers — created only after user confirmation."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.agents.answer_no_context import department_contact
from app.agents.timing import ensure_timings, timed
from app.tickets.notify import notify_ticket_opened
from app.tickets.store import TICKET_TYPE_ESCALATION, TICKET_TYPE_UNKNOWN, create_ticket

logger = logging.getLogger(__name__)

TICKET_CONFIRMED_ANSWER = (
    "Your support ticket has been opened. The helpdesk team will follow up with you."
)

TICKET_DECLINED_ANSWER = (
    "No problem. If you still need help, contact {contact} or try rephrasing your question."
)


def create_ticket_from_payload(
    payload: Dict[str, Any],
    *,
    user_id: str | None,
    user_email: str | None,
) -> Dict[str, Any]:
    ticket_type = payload.get("ticket_type") or TICKET_TYPE_UNKNOWN
    severity = payload.get("severity") or "routine"
    ticket = create_ticket(
        question=payload.get("question") or "",
        normalized_query=payload.get("normalized_query") or "",
        reason=payload.get("reason") or "kb_not_recognized",
        ticket_type=ticket_type,
        department=payload.get("department") or "unknown",
        severity=severity,
        attempted_depts=list(payload.get("attempted_depts") or []),
        created_by_user_id=user_id,
        created_by_email=user_email,
    )
    if (severity or "").lower() == "high" or ticket_type == TICKET_TYPE_ESCALATION:
        try:
            notify_ticket_opened(ticket)
        except Exception as exc:
            logger.warning(
                "ticket notify failed ticket_id=%s: %s",
                ticket["id"],
                exc,
            )
    logger.info(
        "ticket created ticket_id=%s type=%s user=%s",
        ticket["id"],
        ticket_type,
        user_email,
    )
    return ticket


def decline_ticket_message(department: str) -> str:
    _, contact = department_contact(department)
    return TICKET_DECLINED_ANSWER.format(contact=contact)


def create_ticket_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy graph node — delegates to payload-based creation."""
    timings = ensure_timings(state)
    with timed(timings, "create_ticket"):
        from app.agents.answer_no_context import build_pending_ticket_payload

        payload = state.get("pending_ticket_payload") or build_pending_ticket_payload(state)
        ticket = create_ticket_from_payload(
            payload,
            user_id=state.get("user_id"),
            user_email=state.get("user_email"),
        )
        severity = payload.get("severity") or "routine"
        return {
            "department": payload.get("department") or "unknown",
            "severity": severity,
            "ticket_id": ticket["id"],
            "answer": TICKET_CONFIRMED_ANSWER,
            "model_used": "hitl_ticket",
            "context_used": False,
            "sources": [],
            "chunks": [],
            "escalated": bool(payload.get("escalated")),
            "escalation_reason": None,
            "pending_ticket_confirmation": False,
            "node_timings": timings,
        }
