"""Classifier agent — Haiku + structured JSON + prompt caching + fallback."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.agents.timing import ensure_timings, timed
from app.config import get_settings
from app.llm.client import cached_system, complete, merge_token_usage

logger = logging.getLogger(__name__)

DEPARTMENTS = ("hr", "it", "compliance", "legal")
ALL_LABELS = DEPARTMENTS + ("unknown",)
SEVERITIES = ("routine", "high")

CLASSIFIER_SYSTEM = """You are the Ampcus Helpdesk routing classifier.
Classify each employee question into exactly one department and one severity.

Departments:
- hr: PTO, benefits, leave, performance, harassment, expenses, remote work policy as HR topic
- it: VPN, passwords, MFA, laptops, software, wifi, phishing, outages
- compliance: data classification, acceptable use, retention, GDPR, gifts, vendor risk, training
- legal: NDAs, contracts, IP, litigation hold, data breach legal response, employment claims, export
- unknown: use ONLY when the question does not clearly fit any department above

Severity:
- routine: standard FAQ / policy lookup
- high: legal risk, data breach, harassment, termination/lawsuit threats, regulatory exposure

Return ONLY valid JSON with keys:
{"department":"hr|it|compliance|legal|unknown","severity":"routine|high","reason":"short explanation"}

If attempted_departments is provided, pick a different department that still fits (or unknown if none fit).
Do not invent policies. Do not answer the user question — only classify.
When unsure, prefer "unknown" over guessing.
"""


def _parse_classification(text: str) -> Optional[Dict[str, str]]:
    text = text.strip()
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
    dept = str(data.get("department", "")).lower().strip()
    sev = str(data.get("severity", "")).lower().strip()
    if sev == "low":
        sev = "routine"
    if sev == "medium":
        sev = "routine"
    reason = str(data.get("reason", "")).strip()
    if dept not in ALL_LABELS or sev not in SEVERITIES:
        return None
    return {"department": dept, "severity": sev, "reason": reason}


# Keyword scores used when Haiku is unavailable — still routes to the right KB.
_DEPT_KEYWORDS: Dict[str, tuple[str, ...]] = {
    "it": (
        "vpn",
        "password",
        "mfa",
        "laptop",
        "wifi",
        "wi-fi",
        "software",
        "phishing",
        "outlook",
        "email",
        "sso",
        "outage",
        "computer",
        "network",
        "printer",
        "slack",
    ),
    "legal": (
        "nda",
        "contract",
        "litigation",
        "lawsuit",
        "breach",
        "intellectual property",
        "ip ",
        "export control",
        "settlement",
        "attorney",
        "legal",
    ),
    "compliance": (
        "gdpr",
        "data classification",
        "retention",
        "acceptable use",
        "vendor risk",
        "dpa",
        "privacy",
        "gift",
        "compliance training",
        "restricted data",
        "confidential data",
    ),
    "hr": (
        "pto",
        "time off",
        "sick leave",
        "parental",
        "benefits",
        "harassment",
        "expense",
        "remote work",
        "performance review",
        "payroll",
        "vacation",
        "hire",
        "onboarding",
    ),
}

_HIGH_KEYWORDS = (
    "breach",
    "harassment",
    "lawsuit",
    "litigation",
    "termination",
    "discrimination",
    "data leak",
    "ransomware",
    "threatened",
)


def heuristic_classify(
    question: str,
    attempted_depts: Optional[List[str]] = None,
) -> Dict[str, str]:
    """Local keyword router. Returns department=unknown when nothing matches."""
    text = (question or "").lower()
    attempted = {d.lower() for d in (attempted_depts or [])}
    scores = {dept: 0 for dept in DEPARTMENTS}
    for dept, words in _DEPT_KEYWORDS.items():
        for word in words:
            if word in text:
                scores[dept] += 1

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_dept, best_score = ranked[0]
    if best_score <= 0:
        return {
            "department": "unknown",
            "severity": "routine",
            "reason": "heuristic_no_match",
        }

    department = "unknown"
    for dept, score in ranked:
        if score > 0 and dept not in attempted:
            department = dept
            break
    if department == "unknown" and best_dept in attempted:
        # All matching depts already tried
        return {
            "department": "unknown",
            "severity": "high" if any(k in text for k in _HIGH_KEYWORDS) else "routine",
            "reason": "heuristic_exhausted_attempted",
        }

    severity = "high" if any(k in text for k in _HIGH_KEYWORDS) else "routine"
    return {
        "department": department,
        "severity": severity,
        "reason": "heuristic_keyword_classifier",
    }


def classify_question(
    question: str,
    attempted_depts: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """LLM classify (Haiku role via Ollama/Anthropic). Failures → unknown HITL ticket."""
    settings = get_settings()
    attempted = [d.lower() for d in (attempted_depts or [])]
    heuristic = heuristic_classify(question, attempted_depts=attempted)
    unknown_fallback = {
        "department": "unknown",
        "severity": heuristic.get("severity") or "routine",
        "reason": "classifier_unknown_fallback",
        "model_used": "unknown",
        "token_usage": {},
    }

    # If Anthropic selected but no key, use heuristic (not a silent HR guess).
    if settings.llm_provider.lower() == "anthropic" and not settings.anthropic_api_key:
        logger.warning("Anthropic provider without API key — heuristic classifier")
        return {**heuristic, "model_used": "heuristic", "token_usage": {}}

    user_payload = {
        "question": question,
        "attempted_departments": attempted,
    }
    try:
        result = complete(
            model=settings.classifier_model,
            system=cached_system(CLASSIFIER_SYSTEM),
            user_content=json.dumps(user_payload),
            max_tokens=256,
        )
        parsed = _parse_classification(result.text)
        if not parsed:
            logger.warning("Classifier parse failure → unknown. raw=%s", result.text[:200])
            # Prefer heuristic if it found a dept; else unknown ticket
            if heuristic.get("department") != "unknown":
                return {
                    **heuristic,
                    "model_used": f"{result.model}|parse_fallback_heuristic",
                    "token_usage": result.token_usage,
                }
            unknown_fallback["token_usage"] = result.token_usage
            unknown_fallback["reason"] = "classifier_parse_failure"
            return unknown_fallback
        if (
            parsed["department"] in attempted
            and parsed["department"] != "unknown"
            and len(attempted) < len(DEPARTMENTS)
        ):
            for alt in DEPARTMENTS:
                if alt not in attempted:
                    parsed["department"] = alt
                    parsed["reason"] = (parsed["reason"] + " | forced_alt_dept").strip(" |")
                    break
            else:
                parsed["department"] = "unknown"
                parsed["reason"] = "no_remaining_departments"
        return {
            **parsed,
            "model_used": f"{result.provider}:{result.model}",
            "token_usage": result.token_usage,
        }
    except Exception:
        logger.exception("Classifier LLM failure — heuristic then unknown")
        if heuristic.get("department") != "unknown":
            return {**heuristic, "model_used": "heuristic_after_llm_error", "token_usage": {}}
        return unknown_fallback


def classify_node(state: Dict[str, Any]) -> Dict[str, Any]:
    timings = ensure_timings(state)
    with timed(timings, "classify"):
        hint = (state.get("department_hint") or "").lower().strip()
        attempted = list(state.get("attempted_depts") or [])
        query = state.get("normalized_query") or state.get("query") or ""

        if hint in DEPARTMENTS and hint not in attempted and not state.get("department"):
            # First pass only: honor hint without LLM if provided
            if int(state.get("retry_count") or 0) == 0 and not attempted:
                logger.info("classify using department_hint=%s", hint)
                return {
                    "department": hint,
                    "severity": "routine",
                    "classify_reason": "department_hint",
                    "node_timings": timings,
                }

        result = classify_question(query, attempted_depts=attempted)
        usage = merge_token_usage(state.get("token_usage"), result.get("token_usage") or {})
        logger.info(
            "classify dept=%s severity=%s reason=%s",
            result["department"],
            result["severity"],
            result.get("reason"),
        )
        return {
            "department": result["department"],
            "severity": result["severity"],
            "classify_reason": result.get("reason", ""),
            "model_used": result.get("model_used", ""),
            "token_usage": usage,
            "node_timings": timings,
        }
