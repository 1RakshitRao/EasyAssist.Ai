"""Security incident detection and urgent escalation responses."""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.agents.answer_no_context import build_pending_ticket_payload
from app.agents.timing import ensure_timings, timed
from app.agents.ticket import create_ticket_from_payload
from app.config import get_settings
from app.tickets.store import TICKET_TYPE_ESCALATION

logger = logging.getLogger(__name__)

# Employee reporting they are a victim — never treat as restricted/off-scope.
SECURITY_INCIDENT_KEYWORDS: tuple[str, ...] = (
    "unauthorized access",
    "unauthorised access",
    "account hacked",
    "account was hacked",
    "my account was",
    "compromised",
    "data breach",
    "security breach",
    "suspicious activity",
    "suspicious login",
    "someone accessed my",
    "accessed my account",
    "files missing",
    "files were deleted",
    "files deleted",
    "ransomware",
    "malware on my",
    "virus on my",
    "phishing email",
    "clicked a phishing",
    "credential theft",
    "stolen password",
    "account takeover",
    "breach of my",
)

# Definitional / policy questions — not active incident reports.
_POLICY_QUESTION_MARKERS: tuple[str, ...] = (
    "what does",
    "what is",
    "what are",
    "define ",
    "definition of",
    "acceptable use",
    " per policy",
    " in the policy",
    "according to policy",
    "policy say",
    "policy state",
    "policy mean",
)

# Reporting patterns — victim language, not attacker requests.
_VICTIM_CONTEXT: tuple[str, ...] = (
    "my account",
    "my work account",
    "my email",
    "my laptop",
    "my computer",
    "my files",
    "my device",
    "i think",
    "i suspect",
    "report",
    "noticed",
    "found",
    "may have been",
    "might have been",
    "was compromised",
    "have been compromised",
)


def is_security_incident(query: str) -> bool:
    """True when an employee is reporting a security incident (not attacking)."""
    text = (query or "").lower().strip()
    if not text:
        return False
    if not any(kw in text for kw in SECURITY_INCIDENT_KEYWORDS):
        return False

    has_victim_context = any(v in text for v in _VICTIM_CONTEXT)
    if any(m in text for m in _POLICY_QUESTION_MARKERS) and not has_victim_context:
        return False

    if has_victim_context:
        return True

    # Strong signals that rarely appear in policy questions
    strong = (
        "account hacked",
        "ransomware",
        "someone accessed my",
        "clicked a phishing",
        "account takeover",
    )
    return any(s in text for s in strong)


def build_security_incident_answer(*, ticket_id: str, sla_hours: int) -> str:
    ref = ticket_id[:8].upper()
    return (
        "Security incident detected — high priority\n\n"
        "I've flagged this as an urgent security incident and opened an "
        f"escalation ticket for IT Security (reference: {ref}).\n\n"
        "Immediate steps:\n"
        "1. Change your password immediately from a different trusted device\n"
        "2. Log out of all active sessions (email, VPN, SSO)\n"
        "3. Do not open suspicious files or links; disconnect from sensitive networks if needed\n"
        "4. Preserve evidence — note times, senders, and filenames; do not delete logs\n\n"
        "IT Security and Compliance have been notified. "
        f"Target response within {sla_hours} hour(s).\n\n"
        f"Ticket ID: {ticket_id}"
    )


def handle_security_incident(state: Dict[str, Any]) -> Dict[str, Any]:
    """Auto-escalate security incident reports with an immediate action plan."""
    timings = ensure_timings(state)
    with timed(timings, "security_incident"):
        settings = get_settings()
        sla_hours = int(settings.escalation_reminder_hours or 2)

        incident_state = {
            **state,
            "department": "it",
            "severity": "high",
            "escalated": True,
            "classify_reason": "security_incident_report",
        }
        payload = build_pending_ticket_payload(incident_state)
        payload["ticket_type"] = TICKET_TYPE_ESCALATION
        payload["department"] = "it"
        payload["severity"] = "high"
        payload["reason"] = "Security incident reported by employee — urgent IT Security review"
        payload["escalated"] = True

        ticket = create_ticket_from_payload(
            payload,
            user_id=state.get("user_id"),
            user_email=state.get("user_email"),
        )
        ticket_id = str(ticket.get("id") or "")

        logger.info(
            "security_incident ticket_id=%s user=%s",
            ticket_id,
            state.get("user_email"),
        )

        return {
            "intent": "security_incident",
            "department": "it",
            "severity": "high",
            "escalated": True,
            "escalation_reason": "Security incident — IT Security escalation opened",
            "ticket_id": ticket_id,
            "answer": build_security_incident_answer(
                ticket_id=ticket_id,
                sla_hours=sla_hours,
            ),
            "model_used": "security_incident",
            "context_used": False,
            "sources": [],
            "pending_ticket_confirmation": False,
            "pending_ticket_payload": None,
            "node_timings": timings,
        }
