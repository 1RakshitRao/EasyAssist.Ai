"""Prompt user to confirm ticket creation after escalated grounded answers."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.agents.answer_no_context import build_no_context_answer, build_pending_ticket_payload
from app.agents.timing import ensure_timings, timed

logger = logging.getLogger(__name__)

_CONFIRM_SUFFIX = "Would you like me to open a support ticket for human review?"


def ticket_confirm_prompt_node(state: Dict[str, Any]) -> Dict[str, Any]:
    timings = ensure_timings(state)
    with timed(timings, "ticket_confirm_prompt"):
        if state.get("ticket_id") or not state.get("escalated"):
            return {"node_timings": timings}

        answer = (state.get("answer") or "").strip()
        department = (state.get("department") or "unknown").lower()
        severity = state.get("severity") or "routine"

        if _CONFIRM_SUFFIX not in answer:
            urgency = build_no_context_answer(
                department=department,
                severity=severity,
                escalated=True,
                include_confirm_prompt=False,
            )
            # Use only the urgency line from the template when chunks were found.
            urgency_line = urgency.split("\n\n")[-1] if severity == "high" else ""
            parts = [answer]
            if urgency_line and urgency_line not in answer:
                parts.append(urgency_line)
            parts.append(_CONFIRM_SUFFIX)
            answer = "\n\n".join(parts)

        payload = build_pending_ticket_payload(state)
        logger.info(
            "ticket_confirm_prompt dept=%s severity=%s",
            department,
            severity,
        )
        return {
            "answer": answer,
            "pending_ticket_confirmation": True,
            "pending_ticket_payload": payload,
            "node_timings": timings,
        }
