"""Dedicated no-context response — honest KB miss guidance without LLM hallucination."""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

from app.agents.timing import ensure_timings, timed
from app.tickets.store import TICKET_TYPE_ESCALATION, TICKET_TYPE_UNKNOWN

logger = logging.getLogger(__name__)

DEPARTMENT_CONTACTS: Dict[str, Tuple[str, str]] = {
    "hr": ("HR", "hr@ampcus.com"),
    "it": ("IT", "it@ampcus.com"),
    "compliance": ("Compliance", "compliance@ampcus.com"),
    "legal": ("Legal", "legal@ampcus.com"),
    "unknown": ("Helpdesk", "helpdesk@ampcus.com"),
}


def department_contact(department: str) -> Tuple[str, str]:
    dept = (department or "unknown").lower().strip()
    return DEPARTMENT_CONTACTS.get(dept, DEPARTMENT_CONTACTS["unknown"])


def build_no_context_answer(
    *,
    department: str,
    severity: str = "routine",
    escalated: bool = False,
    include_confirm_prompt: bool = True,
) -> str:
    dept_label, contact = department_contact(department)
    lines = [
        "I couldn't find information about this in our knowledge base.",
        f"For {dept_label} questions, please contact {contact}.",
        "You can also try rephrasing your question differently.",
    ]
    if (severity or "").lower() == "high" or escalated:
        lines.append(
            "This looks time-sensitive — I recommend opening a support ticket "
            "so the team can respond quickly."
        )
    if include_confirm_prompt:
        lines.append("Would you like me to open a support ticket for human review?")
    return "\n\n".join(lines)


def build_pending_ticket_payload(state: Dict[str, Any]) -> Dict[str, Any]:
    severity = state.get("severity") or "routine"
    escalated = bool(state.get("escalated"))
    department = (state.get("department") or "unknown").lower()
    if escalated and department != "unknown":
        ticket_type = TICKET_TYPE_ESCALATION
        reason = f"High-severity {department.upper()} query — human desk review required."
        ticket_department = department
    else:
        ticket_type = TICKET_TYPE_UNKNOWN
        reason = state.get("classify_reason") or "kb_not_recognized"
        if not (state.get("chunks") or []):
            reason = "kb_not_recognized"
        ticket_department = "unknown"

    return {
        "question": state.get("query") or "",
        "normalized_query": state.get("normalized_query") or "",
        "department": ticket_department,
        "severity": severity,
        "reason": reason,
        "attempted_depts": list(state.get("attempted_depts") or []),
        "ticket_type": ticket_type,
        "escalated": escalated,
        "classify_reason": state.get("classify_reason") or "",
    }


def answer_no_context_node(state: Dict[str, Any]) -> Dict[str, Any]:
    timings = ensure_timings(state)
    with timed(timings, "answer_no_context"):
        department = (state.get("department") or "unknown").lower()
        severity = state.get("severity") or "routine"
        escalated = bool(state.get("escalated"))
        answer = build_no_context_answer(
            department=department,
            severity=severity,
            escalated=escalated,
        )
        payload = build_pending_ticket_payload(state)
        logger.info(
            "answer_no_context dept=%s severity=%s escalated=%s",
            department,
            severity,
            escalated,
        )
        return {
            "department": department if department != "unknown" else "unknown",
            "severity": severity,
            "answer": answer,
            "model_used": "no_context",
            "context_used": False,
            "sources": [],
            "ticket_id": None,
            "pending_ticket_confirmation": True,
            "pending_ticket_payload": payload,
            "node_timings": timings,
        }
