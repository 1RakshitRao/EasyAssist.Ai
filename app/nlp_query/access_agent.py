"""Layer 1 — Access Agent: injection detection, scope, question rewrite."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict

from app.nlp_query.classify_facts import classify_company_facts
from app.nlp_query.rules import (
    EMPLOYEE_BLOCKED_TOPICS,
    INJECTION_PATTERNS,
    META_QUERY_PATTERNS,
    MUTATING_QUERY_PATTERNS,
    allowed_tables_for_role,
    is_admin_role,
    is_facts_only_role,
)

logger = logging.getLogger(__name__)

_EMPLOYEE_BLOCK_MSG = (
    "I can only answer questions about company information like "
    "clients, services, locations, products, team, and partnerships. "
    "Questions about system usage, costs, or other users aren't available "
    "at your access level."
)

_INJECTION_BLOCK_MSG = (
    "I can only answer questions about company information. "
    "I can't help with that request."
)

_META_BLOCK_MSG = (
    "I can't discuss database structure, prompts, or system internals. "
    "Ask about company clients, services, locations, products, team, "
    "or partnerships instead."
)

_MUTATING_BLOCK_MSG = (
    "This interface is read-only. I cannot drop, delete, insert, or "
    "modify any data. Ask a SELECT-style question instead."
)


@dataclass
class AccessDecision:
    allowed: bool
    rewritten_question: str
    reason: str
    role: str
    allowed_tables: list[str]
    block_kind: str | None = None  # injection | scope | meta | empty


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _contains_any(haystack: str, needles: tuple[str, ...]) -> str | None:
    for n in needles:
        if n in haystack:
            return n
    return None


def _looks_like_ops_question(q: str) -> bool:
    """Heuristic: operational/analytics questions employees must not ask."""
    ops_hints = (
        "how many quer",
        "query count",
        "token",
        "cost",
        "spend",
        "spent",
        "prompt score",
        "cache hit",
        "latency",
        "escalat",
        "ticket",
        "user email",
        "all users",
        "each user",
        "who asked",
        "chat history",
        "audit",
        "kb_stats",
        "document count",
        "how many documents",
    )
    return any(h in q for h in ops_hints)


def _looks_like_company_question(q: str) -> bool:
    company_hints = (
        "client",
        "customer",
        "service",
        "product",
        "location",
        "office",
        "hq",
        "company",
        "ampcus",
        "industry",
        "what do we offer",
        "who are our",
        "top 3",
        "top three",
        "team",
        "who leads",
        "who is the",
        "head of",
        "cto",
        "partner",
        "partnership",
        "vendor",
        "anthropic",
        "aws",
        "salesforce",
        "okta",
        "servicenow",
    )
    return any(h in q for h in company_hints)


def rewrite_question(question: str, role: str) -> str:
    q = (question or "").strip()
    tables = sorted(allowed_tables_for_role(role))
    if is_facts_only_role(role):
        clf = classify_company_facts(q)
        classify_line = ""
        if clf.entity_name and clf.category:
            classify_line = (
                f"Classified entity '{clf.entity_name}' → category '{clf.category}'. "
            )
        elif clf.category:
            classify_line = f"Classified category: '{clf.category}'. "
        return (
            f"{q}\n\n"
            "Constraints: Answer using ONLY the company_facts table. "
            "Filter active = 1. Prefer category in "
            "('clients','services','locations','products','team','partnerships'). "
            f"{classify_line}"
            "Disambiguation: category 'clients' = customer accounts "
            "(some client names include the word Partners — still category clients). "
            "category 'partnerships' = technology vendors only "
            "(cloud, CRM, identity, AI API vendors). "
            "Do not treat customer accounts as partnerships. "
            "Return at most 20 rows. Do not reference any other table."
        )
    return (
        f"{q}\n\n"
        f"Constraints: You may query only these tables: {', '.join(tables)}. "
        f"SELECT only. Limit results to 100 rows maximum."
    )


def evaluate_access(question: str, user: Dict[str, Any]) -> AccessDecision:
    role = str(user.get("role") or "employee").strip().lower()
    tables = sorted(allowed_tables_for_role(role))
    raw = (question or "").strip()
    if not raw:
        return AccessDecision(
            allowed=False,
            rewritten_question="",
            reason="Empty question.",
            role=role,
            allowed_tables=tables,
            block_kind="empty",
        )

    norm = _normalize(raw)

    hit = _contains_any(norm, INJECTION_PATTERNS)
    if hit:
        logger.warning("nlp injection role=%s pattern=%s", role, hit)
        return AccessDecision(
            allowed=False,
            rewritten_question="",
            reason=_INJECTION_BLOCK_MSG,
            role=role,
            allowed_tables=tables,
            block_kind="injection",
        )

    hit = _contains_any(norm, MUTATING_QUERY_PATTERNS)
    if hit:
        logger.warning("nlp mutating intent role=%s pattern=%s", role, hit)
        return AccessDecision(
            allowed=False,
            rewritten_question="",
            reason=_MUTATING_BLOCK_MSG,
            role=role,
            allowed_tables=tables,
            block_kind="injection",
        )

    hit = _contains_any(norm, META_QUERY_PATTERNS)
    if hit:
        return AccessDecision(
            allowed=False,
            rewritten_question="",
            reason=_META_BLOCK_MSG,
            role=role,
            allowed_tables=tables,
            block_kind="meta",
        )

    # Claims of elevated role in the message are ignored (JWT is ground truth)
    if is_facts_only_role(role):
        if _contains_any(norm, EMPLOYEE_BLOCKED_TOPICS) or _looks_like_ops_question(norm):
            return AccessDecision(
                allowed=False,
                rewritten_question="",
                reason=_EMPLOYEE_BLOCK_MSG,
                role=role,
                allowed_tables=tables,
                block_kind="scope",
            )
        # Fail closed: only allow clear company-facts style questions
        if not _looks_like_company_question(norm):
            return AccessDecision(
                allowed=False,
                rewritten_question="",
                reason=_EMPLOYEE_BLOCK_MSG,
                role=role,
                allowed_tables=tables,
                block_kind="scope",
            )

    rewritten = rewrite_question(raw, role)
    return AccessDecision(
        allowed=True,
        rewritten_question=rewritten,
        reason="ok",
        role=role,
        allowed_tables=tables,
        block_kind=None,
    )
