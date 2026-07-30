"""Escalate node — high-severity legal/HR creates an open HITL escalation ticket."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.agents.timing import ensure_timings, timed
from app.config import get_settings
from app.tickets.store import TICKET_TYPE_ESCALATION, create_ticket

logger = logging.getLogger(__name__)


def should_escalate(department: str, severity: str) -> bool:
    settings = get_settings()
    return severity == "high" and department.lower() in settings.escalate_department_list


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
        )
        user_reason = (
            f"{reason} You should hear back within 2 hours. "
            f"Escalation ticket: {ticket['id']}"
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
