"""Escalate node — high-severity queries create an open HITL escalation ticket."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.agents.timing import ensure_timings, timed
from app.config import get_settings
from app.tickets.notify import notify_ticket_opened
from app.tickets.store import TICKET_TYPE_ESCALATION, create_ticket

logger = logging.getLogger(__name__)


def should_escalate(department: str, severity: str) -> bool:
    """Open a HITL escalation ticket for any high-severity classified query."""
    _ = department  # kept for call-site compatibility; all depts escalate when high
    return (severity or "").lower().strip() == "high"


def should_open_high_ticket(severity: str) -> bool:
    return (severity or "").lower().strip() == "high"


def escalate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    timings = ensure_timings(state)
    with timed(timings, "escalate"):
        department = (state.get("department") or "").lower()
        severity = state.get("severity") or "routine"
        if not should_escalate(department, severity):
            logger.info("escalate skipped dept=%s severity=%s", department, severity)
            return {
                "escalated": False,
                "escalation_reason": None,
                "node_timings": timings,
            }

        settings = get_settings()
        in_classic_list = department in settings.escalate_department_list
        reason = (
            f"High-severity {department.upper()} query — human desk review required."
        )
        ticket = create_ticket(
            question=state.get("query") or "",
            normalized_query=state.get("normalized_query") or "",
            reason=reason,
            ticket_type=TICKET_TYPE_ESCALATION,
            department=department,
            severity=severity,
            attempted_depts=list(state.get("attempted_depts") or []),
            created_by_user_id=state.get("user_id"),
            created_by_email=state.get("user_email"),
        )
        try:
            notify_ticket_opened(ticket)
        except Exception as exc:
            logger.warning("escalate notify failed ticket_id=%s: %s", ticket["id"], exc)

        hours = int(settings.escalation_reminder_hours)
        label = "escalation" if in_classic_list else "high-severity"
        user_reason = (
            f"{reason} You should hear back within {hours} hours. "
            f"{label.capitalize()} ticket: {ticket['id']}"
        )
        logger.info(
            "escalate triggered dept=%s severity=%s ticket_id=%s",
            department,
            severity,
            ticket["id"],
        )
        return {
            "escalated": True,
            "escalation_reason": user_reason,
            "ticket_id": ticket["id"],
            "node_timings": timings,
        }
