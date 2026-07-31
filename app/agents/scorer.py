"""Prompt quality scorer — Haiku role + heuristic fallback."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.llm.client import cached_system, complete

logger = logging.getLogger(__name__)

SCORER_SYSTEM = """You score employee helpdesk prompts for quality on a 1–10 scale.

Rubric (sum then clamp to 1–10):
- Specificity 0–3: concrete system/topic/error vs vague
- Clarity 0–3: clear question vs rambling/ambiguous
- Context 0–2: relevant details (error text, when, what tried)
- Actionability 0–2: answerable as a helpdesk request

Return ONLY valid JSON:
{"score":1-10,"issues":["short issue",...],"improved_query":"rewritten clearer prompt","reason":"one sentence"}

Be constructive. improved_query should be a better version of the same ask.
"""


def _clamp_score(n: Any) -> int:
    try:
        v = int(round(float(n)))
    except (TypeError, ValueError):
        v = 5
    return max(1, min(10, v))


def parse_score_response(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None
    data = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    if not isinstance(data, dict):
        return None
    issues = data.get("issues") or []
    if not isinstance(issues, list):
        issues = [str(issues)]
    issues = [str(i).strip() for i in issues if str(i).strip()][:8]
    improved = str(data.get("improved_query") or "").strip()
    reason = str(data.get("reason") or "").strip()
    return {
        "score": _clamp_score(data.get("score")),
        "issues": issues,
        "improved_query": improved,
        "reason": reason or "scored",
    }


def heuristic_score(query: str) -> Dict[str, Any]:
    """Offline scoring when LLM is unavailable — length/keyword heuristic."""
    q = (query or "").strip()
    lower = q.lower()
    issues: List[str] = []
    specificity = 0
    clarity = 0
    context = 0
    actionability = 0

    words = re.findall(r"[a-z0-9']+", lower)
    n = len(words)

    specific_markers = (
        "vpn",
        "password",
        "mfa",
        "outlook",
        "pto",
        "leave",
        "laptop",
        "error",
        "nda",
        "policy",
        "benefits",
        "wifi",
        "sso",
        "ticket",
        "expense",
    )
    if any(m in lower for m in specific_markers):
        specificity += 2
    if n >= 8:
        specificity += 1
    specificity = min(3, specificity)
    if specificity < 2:
        issues.append("Too vague — name the system or policy")

    if "?" in q or lower.startswith(("how", "what", "why", "when", "where", "can", "do")):
        clarity += 2
    if 5 <= n <= 60:
        clarity += 1
    elif n < 4:
        issues.append("Too short to understand the ask")
    elif n > 80:
        issues.append("Too long / rambling — focus the question")
    clarity = min(3, clarity)

    context_markers = (
        "error",
        "message",
        "tried",
        "when",
        "since",
        "after",
        "code",
        "screenshot",
        "yesterday",
        "today",
        "because",
    )
    hits = sum(1 for m in context_markers if m in lower)
    context = min(2, hits)
    if context == 0:
        issues.append("Add context (error text, timing, what you already tried)")

    if any(
        p in lower
        for p in ("how do i", "how to", "what is", "where can", "help me", "need to")
    ) or "?" in q:
        actionability += 2
    elif n >= 6:
        actionability += 1
    else:
        issues.append("Make it a clear request an agent can act on")
    actionability = min(2, actionability)

    total = specificity + clarity + context + actionability
    score = _clamp_score(total if total >= 1 else 1)

    improved = q
    if not improved.endswith("?"):
        improved = improved.rstrip(".!") + "?"
    if specificity < 2:
        improved = f"Regarding [system/policy]: {improved}"
    if context < 1:
        improved = (
            improved.rstrip("?")
            + " — I see [error/details], and I already tried [steps]?"
        )

    return {
        "score": score,
        "issues": issues or (["Looks okay"] if score >= 7 else ["Could be clearer"]),
        "improved_query": improved,
        "reason": "heuristic_score",
    }


def score_prompt(query: str) -> Dict[str, Any]:
    """Score a user prompt; falls back to heuristic when LLM unavailable."""
    settings = get_settings()
    fallback = heuristic_score(query)

    if settings.llm_provider.lower() == "anthropic" and not settings.anthropic_api_key:
        return {**fallback, "model_used": "heuristic"}

    try:
        result = complete(
            model=settings.classifier_model,
            system=cached_system(SCORER_SYSTEM),
            user_content=json.dumps({"query": query}),
            max_tokens=400,
        )
        parsed = parse_score_response(result.text)
        if not parsed:
            logger.warning("Scorer parse failure — heuristic. raw=%s", result.text[:200])
            return {**fallback, "model_used": f"{result.model}|parse_fallback"}
        return {
            **parsed,
            "model_used": result.model,
            "token_usage": result.token_usage,
        }
    except Exception as exc:
        logger.warning("Scorer LLM failed — heuristic: %s", exc)
        return {**fallback, "model_used": "heuristic"}
