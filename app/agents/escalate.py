"""Escalate node — flag high-severity queries; ticket created only after user confirms."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.agents.timing import ensure_timings, timed
from app.audit.query_trace import tracer_from_state
from app.config import get_settings

logger = logging.getLogger(__name__)


def should_escalate(department: str, severity: str) -> bool:
    """Flag high-severity classified queries for escalation handling."""
    _ = department
    return (severity or "").lower().strip() == "high"


def should_open_high_ticket(severity: str) -> bool:
    return (severity or "").lower().strip() == "high"


def escalate_node(state: Dict[str, Any]) -> Dict[str, Any]:
    timings = ensure_timings(state)
    tracer = tracer_from_state(state)
    if tracer:
        tracer.agent_started("ESCALATION", "Evaluating escalation criteria")
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
        hours = int(settings.escalation_reminder_hours)
        reason = (
            f"High-severity {department.upper()} query — human desk review required."
        )
        user_reason = (
            f"This is flagged as high severity. The appropriate {department.upper()} "
            f"team should review this promptly (target response within {hours} hours)."
        )
        logger.info(
            "escalate flagged dept=%s severity=%s (awaiting user ticket confirm)",
            department,
            severity,
        )
        if tracer:
            tracer.escalated(None, [f"{department.upper()} desk"])
            tracer.agent_done("ESCALATION", "High severity flagged for ticket confirm")
        return {
            "escalated": True,
            "escalation_reason": user_reason,
            "classify_reason": reason,
            "ticket_id": None,
            "node_timings": timings,
        }
