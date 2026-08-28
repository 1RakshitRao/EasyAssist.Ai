"""Supervisor Agent — single entry routing for all chat messages."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from app.agents.security_incident import is_security_incident
from app.config import get_settings
from app.documents.inline_text import detect_inline_analysis, is_inline_text_analysis
from app.llm.client import cached_system, complete, is_llm_configured, resolve_classifier_model

logger = logging.getLogger(__name__)

INTENTS = (
    "conversational",
    "helpdesk_query",
    "security_incident",
    "nlp_query",
    "document_op",
    "onboarding_query",
    "reservation_query",
    "infrastructure_info",
    "infrastructure_action",
    "restricted",
    "out_of_scope",
)

CONFIDENCE_LEVELS = ("high", "medium", "low")

DOCUMENT_OPERATIONS = (
    "summarize",
    "takeaways",
    "action_items",
    "explain_simply",
    "find_risks",
    "ask_question",
    "add_to_kb",
)

# Supervisor prompt names → codebase document op ids
_DOCUMENT_OP_MAP = {
    "summarize": "summarize",
    "takeaways": "takeaways",
    "action_items": "actions",
    "explain_simply": "explain",
    "find_risks": "risks",
    "ask_question": "ask",
    "add_to_kb": "push_to_kb",
}

KEYWORD_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "conversational",
        (
            "hello",
            "hi ",
            "hi,",
            "hey",
            "thanks",
            "thank you",
            "bye",
            "goodbye",
            "what can you do",
            "how do you work",
            "never mind",
            "cancel",
        ),
    ),
    (
        "onboarding_query",
        (
            "onboarding",
            "checklist",
            "first day",
            "mfa setup",
            "adp",
            "i-9",
            "i9",
            "direct deposit",
            "tax form",
            "mark as done",
            "completed my",
            "new employee",
        ),
    ),
    (
        "reservation_query",
        (
            "guesthouse",
            "guest house",
            "reservation",
            "available next",
            "check in",
            "check out",
            "cancel my booking",
            "modify my stay",
        ),
    ),
    (
        "infrastructure_info",
        (
            "where is the printer",
            "nearest printer",
            "conference room",
            "meeting room",
            "wifi password",
            "wi-fi password",
            "how do i connect to the conference",
            "visitor parking",
            "building access",
            "how do i book conference",
        ),
    ),
    (
        "infrastructure_action",
        (
            "print this",
            "print it",
            "send to printer",
            "book a meeting",
            "book conference",
            "reserve a room for",
            "book a conference room",
        ),
    ),
    (
        "nlp_query",
        (
            "our clients",
            "our offices",
            "our services",
            "our products",
            "who leads",
            "group president",
            "vice president",
            "executive vice",
            "senior vice",
            "our team",
            "leadership",
            "who is the ampcus",
            "who is our",
            "which office",
            "how many employees",
            "our partners",
            "company president",
            "ampcus president",
        ),
    ),
    (
        "out_of_scope",
        ("joke", "weather", "sports", "recipe", "movie", "song", "game"),
    ),
)

RESTRICTED_PATTERNS = (
    "show all users",
    "show me all users",
    "list all users",
    "audit log",
    "show me everyone",
    "how much did everyone spend",
    "all user emails",
    "dump the database",
    "show all queries",
    "admin dashboard",
    "ignore your",
    "forget your rules",
    "pretend you are",
    "you are now",
    "disregard",
    "override your",
    "your new instructions",
)

SUPERVISOR_SYSTEM_TEMPLATE = """You are the Supervisor Agent for an enterprise internal AI assistant.

Your only job is to read the user's message and return a routing decision.
You never answer the question. You never retrieve information.
You only classify intent and route.

The user's role is provided to you. Use it to inform routing decisions.

Return ONLY this JSON — no markdown, no explanation, nothing else:
{{
  "intent": "<one of the eleven intents below>",
  "confidence": "high | medium | low",
  "reason": "<one sentence explaining your decision>",
  "document_operation": "<summarize|takeaways|action_items|explain_simply|find_risks|ask_question|add_to_kb|null>"
}}

━━━ THE ELEVEN INTENTS ━━━

conversational
  Greetings, farewells, thank yous, small talk, questions about what
  the system can do, requests to explain itself.
  Examples: "hello", "thanks", "what can you help me with?"

helpdesk_query
  A genuine work-related question that requires searching a knowledge
  base of HR, IT, Compliance, or Legal policy documents.
  Examples: "how many leave days do I get?", "my VPN won't connect"

security_incident
  An employee REPORTING they may be the victim of a security issue —
  unauthorized access, compromised account, suspicious activity, ransomware,
  missing files, phishing they clicked, or data breach affecting them.
  This is IN SCOPE. The employee is reporting an incident, not asking
  how to hack or gain unauthorized access.
  Examples: "I think someone accessed my account", "my files may have
  been compromised", "I clicked a phishing link"

nlp_query
  A question about factual company data — clients, services, office
  locations, products, team leadership, technology partnerships.
  Examples: "who are our top clients?", "which office has the most employees?"

document_op
  The user wants an operation on an uploaded document in this session.
  Set document_operation to the specific operation requested.
  Only use when context says a document has been uploaded.

onboarding_query
  A new employee asking about personal onboarding tasks, checklist,
  or first-week setup. Only for employees in their first {onboarding_days} days.
  Examples: "show my onboarding checklist", "I've completed my MFA setup"

reservation_query
  Guesthouse booking, availability, cancellations, or guesthouse details.
  Examples: "book the guesthouse for next week", "is the guesthouse available?"

infrastructure_info
  Questions about office infrastructure answerable from IT knowledge base:
  printers, conference rooms, Wi-Fi, parking, building access, cafeteria.
  Examples: "where is the nearest printer?", "how do I book Conference Room A?",
  "what's the Wi-Fi password?", "where is visitor parking?"

infrastructure_action
  The employee wants to DO something with office infrastructure.
  Examples: "print this document", "book a conference room tomorrow at 2pm",
  "reserve a meeting room for 4 people"
  NOT guesthouse — that is reservation_query.

restricted
  User asks for data beyond their access level (admin dumps, audit logs,
  all users). NOT for employees reporting unauthorized access TO THEIR
  OWN account — that is security_incident.
  Examples: "show me all users", "show the audit log"

out_of_scope
  Nothing work-related. Examples: "tell me a joke", "what's the weather?"

━━━ ROUTING RULES ━━━

1. Policy doc → helpdesk_query; company fact → nlp_query
2. Employee reporting security breach/compromised account → security_incident
3. Office printer/room/parking questions → infrastructure_info; print/book actions → infrastructure_action
4. Guesthouse → reservation_query; conference/meeting room → infrastructure_info or infrastructure_action
5. document_op when an uploaded document is in session OR the user pasted substantial
   text with an analysis command (summarize, takeaways, action items, explain, risks)
6. onboarding_query only when joining_date is recent (within {onboarding_days} days)
7. restricted takes priority over other intents EXCEPT security_incident reports
8. Never classify as out_of_scope if there is any work-related angle
"""


def _supervisor_system_prompt() -> str:
    days = int(get_settings().onboarding_window_days or 7)
    return SUPERVISOR_SYSTEM_TEMPLATE.format(onboarding_days=days)


def _parse_supervisor_json(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    intent = str(data.get("intent") or "").lower().strip()
    confidence = str(data.get("confidence") or "medium").lower().strip()
    if confidence not in CONFIDENCE_LEVELS:
        confidence = "medium"
    reason = str(data.get("reason") or "").strip()
    doc_op = data.get("document_operation")
    if doc_op is not None and str(doc_op).lower() in ("null", "none", ""):
        doc_op = None
    elif doc_op is not None:
        doc_op = str(doc_op).lower().strip()
    if intent not in INTENTS:
        return None
    return {
        "intent": intent,
        "confidence": confidence,
        "reason": reason or f"Classified as {intent}",
        "document_operation": doc_op,
    }


def normalize_document_operation(op: Optional[str]) -> Optional[str]:
    """Map supervisor operation names to codebase document op ids."""
    if not op:
        return None
    key = str(op).lower().strip()
    return _DOCUMENT_OP_MAP.get(key, key if key in _DOCUMENT_OP_MAP.values() else None)


def _is_restricted(query: str, user_role: str) -> bool:
    """Hard-coded restriction patterns for employees."""
    role = (user_role or "employee").lower().strip()
    if role in ("admin", "agent"):
        return False
    q = query.lower()
    return any(p in q for p in RESTRICTED_PATTERNS)


def _keyword_fallback(query: str) -> Dict[str, Any]:
    q = query.lower()
    for intent, keywords in KEYWORD_RULES:
        for kw in keywords:
            if kw.endswith(" "):
                if re.search(rf"(?<![a-z]){re.escape(kw.strip())}\b", q):
                    return {
                        "intent": intent,
                        "confidence": "low",
                        "reason": "Keyword match fallback — LLM unavailable",
                        "document_operation": None,
                    }
            elif kw in q:
                return {
                    "intent": intent,
                    "confidence": "low",
                    "reason": "Keyword match fallback — LLM unavailable",
                    "document_operation": None,
                }
    return {
        "intent": "helpdesk_query",
        "confidence": "low",
        "reason": "Default fallback — no keyword match, attempting KB search",
        "document_operation": None,
    }


def _apply_post_validation(
    result: Dict[str, Any],
    *,
    query: str,
    user_role: str,
    has_document: bool,
    onboarding_active: bool,
) -> Dict[str, Any]:
    out = dict(result)

    if is_security_incident(query):
        out["intent"] = "security_incident"
        out["reason"] = "Employee reporting a security incident — urgent escalation"
        out["document_operation"] = None
        return out

    if _is_restricted(query, user_role):
        out["intent"] = "restricted"
        out["reason"] = "Query requests data beyond employee access level"
        out["document_operation"] = None
        return out

    if out.get("intent") == "document_op":
        inline = is_inline_text_analysis(query)
        if not has_document and not inline:
            out["intent"] = "conversational"
            out["reason"] = "Document operation requested but no document uploaded"
            out["document_operation"] = None
        else:
            op = normalize_document_operation(out.get("document_operation"))
            if not op and inline:
                op = detect_inline_analysis(query) or "summarize"
            if not op:
                op = "summarize"
            out["document_operation"] = op
            if op == "push_to_kb" and user_role.lower() != "admin":
                out["document_operation"] = "summarize"
                out["reason"] = (out.get("reason") or "") + " (KB push requires admin)"

    if out.get("intent") == "onboarding_query" and not onboarding_active:
        out["intent"] = "helpdesk_query"
        out["reason"] = "Onboarding inactive — routing to helpdesk KB"
        out["document_operation"] = None

    if out.get("intent") != "document_op":
        out["document_operation"] = None

    return out


def supervise(
    query: str,
    *,
    user_role: str = "employee",
    user_email: str = "",
    has_document: bool = False,
    joining_date: Optional[str] = None,
    onboarding_active: bool = False,
) -> Dict[str, Any]:
    """
    Classify intent and return routing metadata only.

    Returns:
        intent, confidence, reason, document_operation (codebase op id or None)
    """
    if is_security_incident(query):
        return {
            "intent": "security_incident",
            "confidence": "high",
            "reason": "Employee reporting a security incident — urgent escalation",
            "document_operation": None,
        }

    if _is_restricted(query, user_role):
        return {
            "intent": "restricted",
            "confidence": "high",
            "reason": "Query requests data beyond employee access level",
            "document_operation": None,
        }

    if is_inline_text_analysis(query):
        op = detect_inline_analysis(query) or "summarize"
        return {
            "intent": "document_op",
            "confidence": "high",
            "reason": "Inline pasted text with analysis command",
            "document_operation": op,
        }

    context_lines = [f"User role: {user_role or 'employee'}"]
    if joining_date:
        context_lines.append(f"Employee joining date: {joining_date}")
    if onboarding_active:
        context_lines.append("Employee is in active onboarding period.")
    else:
        context_lines.append("Employee is NOT in active onboarding period.")
    if has_document:
        context_lines.append("A document has been uploaded in this session.")
    else:
        context_lines.append("No document uploaded in this session.")

    user_message = "\n".join(context_lines) + f"\n\nUser message: {query}"

    try:
        llm = complete(
            model=resolve_classifier_model(),
            system=cached_system(_supervisor_system_prompt()),
            messages=[{"role": "user", "content": user_message}],
            max_tokens=200,
        )
        parsed = _parse_supervisor_json(llm.text or "")
        if not parsed:
            logger.warning("Supervisor parse failure raw=%s", (llm.text or "")[:200])
            result = _keyword_fallback(query)
        else:
            result = parsed
    except Exception as exc:
        logger.error("Supervisor LLM error: %s", exc)
        result = _keyword_fallback(query)

    final = _apply_post_validation(
        result,
        query=query,
        user_role=user_role,
        has_document=has_document,
        onboarding_active=onboarding_active,
    )

    logger.info(
        "Supervisor → intent=%s confidence=%s user=%s",
        final.get("intent"),
        final.get("confidence"),
        user_email,
    )
    return final
