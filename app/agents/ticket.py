"""HITL ticket node — unknown / unanswered queries go to human review."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.agents.timing import ensure_timings, timed
from app.tickets.notify import notify_ticket_opened
from app.tickets.store import TICKET_TYPE_UNKNOWN, create_ticket

logger = logging.getLogger(__name__)

TICKET_USER_MESSAGE = (
    "I could not confidently route or answer this from the knowledge base. "
    "A support ticket has been created for human review (department: unknown). "
    "An admin will classify it and, once approved, add the answer to the knowledge base."
)


def create_ticket_node(state: Dict[str, Any]) -> Dict[str, Any]:
    timings = ensure_timings(state)
    with timed(timings, "create_ticket"):
        reason = state.get("classify_reason") or "kb_not_recognized"
        if not (state.get("chunks") or []):
            reason = "kb_not_recognized"
        severity = state.get("severity") or "routine"
        ticket = create_ticket(
            question=state.get("query") or "",
            normalized_query=state.get("normalized_query") or "",
            reason=reason,
            ticket_type=TICKET_TYPE_UNKNOWN,
            department="unknown",
            severity=severity,
            attempted_depts=list(state.get("attempted_depts") or []),
            created_by_user_id=state.get("user_id"),
            created_by_email=state.get("user_email"),
        )
        if (severity or "").lower() == "high":
            try:
                notify_ticket_opened(ticket)
            except Exception as exc:
                logger.warning(
                    "unknown high-severity notify failed ticket_id=%s: %s",
                    ticket["id"],
                    exc,
                )
        logger.info("create_ticket_node ticket_id=%s reason=%s", ticket["id"], reason)
        return {
            "department": "unknown",
            "severity": severity,
            "ticket_id": ticket["id"],
            "answer": (
                "I could not find this in the Ampcus knowledge base. "
                "An unknown ticket was opened for human review so an admin can "
                f"add the answer to the KB. Ticket ID: {ticket['id']}"
            ),
            "model_used": "hitl_ticket",
            "context_used": False,
            "sources": [],
            "chunks": [],
            "escalated": False,
            "escalation_reason": None,
            "node_timings": timings,
        }
