"""Onboarding chat agent — checklist, completion, and RAG handoff."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Dict, List, Literal, Optional

from app.agents.graph import run_pipeline
from app.config import get_settings
from app.onboarding import store
from app.onboarding.reminder_templates import (
    build_checklist_payload,
    build_checklist_response,
    build_welcome_message,
)

SubIntent = Literal["show_checklist", "mark_complete", "ask_question"]

CHECKLIST_PATTERNS = (
    r"\bchecklist\b",
    r"\bwhat do i need\b",
    r"\bwhat('s| is) pending\b",
    r"\bmy tasks\b",
    r"\bshow my tasks\b",
    r"\bonboarding progress\b",
    r"\bwhere do i start\b",
    r"\bwhat do i need to do\b",
    r"\bfirst day\b",
    r"\bfirst week\b",
    r"\bnew hire\b",
    r"\bgetting started\b",
    r"\bwhat (am i|should i) (supposed|suppose|meant|need) to do\b",
    r"\bwhat do i do (on|for)\b",
)

COMPLETION_PATTERNS = (
    r"\b(completed|finished|done)\b",
    r"\bmark\b.*\b(done|complete)\b",
    r"\bi('ve| have) (set up|setup|completed|finished|done)\b",
    r"\bi set up\b",
)

GENERIC_OPENERS = (
    r"^(hi|hello|hey|good morning|good afternoon)\b",
    r"^$",
)


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().strip().split())


def detect_sub_intent(query: str) -> SubIntent:
    q = _normalize(query)
    for pat in COMPLETION_PATTERNS:
        if re.search(pat, q):
            return "mark_complete"
    for pat in CHECKLIST_PATTERNS:
        if re.search(pat, q):
            return "show_checklist"
    return "ask_question"


def is_generic_opener(query: str) -> bool:
    q = _normalize(query)
    for pat in GENERIC_OPENERS:
        if re.search(pat, q):
            return True
    return len(q) <= 3


def _task_match_tokens(task: Dict[str, Any]) -> set[str]:
    parts = [
        task.get("task_key") or "",
        task.get("task_title") or "",
        task.get("category") or "",
    ]
    tokens: set[str] = set()
    for part in parts:
        for word in re.split(r"[\W_]+", part.lower()):
            if len(word) >= 3:
                tokens.add(word)
    return tokens


def extract_task_key(query: str, tasks: List[Dict[str, Any]]) -> Optional[str]:
    q = _normalize(query)
    q_tokens = {w for w in re.split(r"[\W_]+", q) if len(w) >= 3}

    best_key: Optional[str] = None
    best_score = 0
    for task in tasks:
        if task.get("status") != "pending":
            continue
        key = task.get("task_key") or ""
        title = (task.get("task_title") or "").lower()
        score = 0
        if key.replace("_", " ") in q or key in q.replace(" ", "_"):
            score += 10
        if key.replace("_", " ") in q:
            score += 8
        overlap = q_tokens & _task_match_tokens(task)
        score += len(overlap) * 2
        for alias in (key, title):
            if alias and alias in q:
                score += 5
        # Common shorthand aliases
        aliases = {
            "setup_mfa": ("mfa", "multi-factor", "authenticator"),
            "payroll_account": ("payroll", "adp"),
            "tax_forms": ("w-4", "w4", "tax"),
            "direct_deposit": ("direct deposit", "bank"),
            "i9_verification": ("i-9", "i9"),
            "benefits_enrollment": ("benefits", "health insurance"),
            "reset_password": ("password",),
            "vpn_setup": ("vpn",),
            "slack_setup": ("slack",),
            "github_access": ("github",),
        }
        for alias in aliases.get(key, ()):
            if alias in q:
                score += 6
        if score > best_score:
            best_score = score
            best_key = key
    return best_key if best_score >= 4 else None


def _task_guidance(task: Dict[str, Any]) -> str:
    title = task.get("task_title") or "Onboarding task"
    desc = (task.get("task_description") or "").strip()
    link = (task.get("link_url") or "").strip()
    lines = [title]
    if desc:
        lines.append(desc)
    if link:
        lines.append(f"Open: {link}")
    if task.get("status") == "completed":
        lines.append("You have already marked this task complete.")
    elif task.get("status") == "skipped":
        lines.append("This task was skipped on your checklist.")
    else:
        lines.append(
            'When finished, tell me — for example: "I\'ve completed '
            f'{title.lower()}" — and I\'ll update your checklist.'
        )
    return "\n".join(lines)


def is_within_onboarding_window(joining_date: str, *, today: date | None = None) -> bool:
    today = today or date.today()
    joined = date.fromisoformat(joining_date)
    window = int(get_settings().onboarding_window_days or 7)
    return joined <= today <= joined + timedelta(days=window - 1)


def matches_onboarding_keywords(query: str) -> bool:
    q = _normalize(query)
    keywords = (
        "onboarding",
        "new hire",
        "new employee",
        "first day",
        "first week",
        "checklist",
        "my tasks",
        "mfa",
        "adp",
        "i-9",
        "i9",
        "payroll",
        "benefits enrollment",
        "direct deposit",
        "w-4",
        "w4",
        "vpn setup",
    )
    return any(kw in q for kw in keywords)


def is_onboarding_context(user_email: str, query: str) -> bool:
    employee = store.get_employee(user_email)
    if not employee or employee.get("onboarding_complete"):
        return False
    if not employee.get("active", True):
        return False
    if not is_within_onboarding_window(employee["joining_date"]):
        sub = detect_sub_intent(query)
        return sub in ("show_checklist", "mark_complete") or matches_onboarding_keywords(
            query
        )
    sub = detect_sub_intent(query)
    if sub in ("show_checklist", "mark_complete"):
        return True
    return matches_onboarding_keywords(query) or True  # in-window → onboarding context


def handle_onboarding_query(
    *,
    user_email: str,
    query: str,
    normalized_query: str,
    department_hint: str | None = None,
    user_id: str | None = None,
    model_preference: str | None = None,
    session_id: str | None = None,
    conversation_history: list | None = None,
    include_welcome: bool = False,
) -> Dict[str, Any]:
    employee = store.get_employee(user_email)
    if not employee:
        return {
            "answer": (
                "Your employee profile hasn't been set up yet. "
                "Please contact HR at hr@ampcus.com."
            ),
            "department": "hr",
            "severity": "routine",
            "sources": [],
            "model_used": "onboarding_agent",
            "context_used": False,
            "token_usage": {},
            "node_timings": {},
            "sub_intent": "no_profile",
        }

    store.set_onboarding_started_at(user_email)
    tasks = store.get_tasks(user_email)
    sub_intent = detect_sub_intent(query)
    from app.audit.query_trace import get_tracer

    if tracer := get_tracer():
        tracer.agent_step("ONBOARDING", f"sub-intent={sub_intent}")

    if sub_intent == "show_checklist":
        body = build_checklist_response(employee, tasks)
        checklist = build_checklist_payload(employee, tasks)
        if include_welcome:
            body = build_welcome_message(employee, tasks) if is_generic_opener(query) else (
                build_welcome_message(employee, tasks) + "\n\n" + body
            )
        return _onboarding_result(body, sub_intent=sub_intent, onboarding_checklist=checklist)

    if sub_intent == "mark_complete":
        task_key = extract_task_key(query, tasks)
        if not task_key:
            body = (
                "I couldn't tell which task you completed. "
                "Try: \"I've set up MFA\" or \"mark payroll as done\"."
            )
            return _onboarding_result(body, sub_intent=sub_intent)

        updated = store.update_task_status_by_key(user_email, task_key, "completed")
        if not updated:
            body = "That task wasn't found on your checklist."
            return _onboarding_result(body, sub_intent=sub_intent)

        fresh_tasks = store.get_tasks(user_email)
        remaining = store.count_pending_tasks(user_email)
        title = updated.get("task_title") or task_key
        checklist = build_checklist_payload(employee, fresh_tasks)
        if remaining == 0:
            body = (
                f"🎉 You've completed all your onboarding tasks! Welcome to the team.\n"
                f"{title} was your last item.\n\n"
                f"{build_checklist_response(employee, fresh_tasks)}"
            )
        else:
            body = (
                f"Great! {title} is marked complete. "
                f"You have {remaining} task{'s' if remaining != 1 else ''} remaining.\n\n"
                f"{build_checklist_response(employee, fresh_tasks)}"
            )
        if include_welcome and not is_generic_opener(query):
            body = build_welcome_message(employee, fresh_tasks) + "\n\n" + body
        elif include_welcome and is_generic_opener(query):
            body = build_welcome_message(employee, fresh_tasks)
            checklist = build_checklist_payload(employee, fresh_tasks)
        return _onboarding_result(
            body, sub_intent=sub_intent, onboarding_checklist=checklist
        )

    # ask_question → checklist task guidance when we can match a task, else RAG
    matched_key = extract_task_key(query, tasks)
    if matched_key:
        matched = next((t for t in tasks if t.get("task_key") == matched_key), None)
        if matched:
            body = _task_guidance(matched)
            checklist = None
            if include_welcome and not is_generic_opener(query):
                body = build_welcome_message(employee, tasks) + "\n\n" + body
                checklist = build_checklist_payload(employee, tasks)
            elif include_welcome and is_generic_opener(query):
                body = build_welcome_message(employee, tasks)
                checklist = build_checklist_payload(employee, tasks)
            return _onboarding_result(
                body, sub_intent="ask_question", onboarding_checklist=checklist
            )

    rag = run_pipeline(
        query=query,
        normalized_query=normalized_query,
        department_hint=department_hint or "hr",
        user_id=user_id,
        user_email=user_email,
        model_preference=model_preference,
        session_id=session_id,
        conversation_history=conversation_history,
    )
    answer = rag.get("answer") or ""
    if answer and not answer.startswith("For your onboarding"):
        answer = f"For your onboarding:\n\n{answer}"
    checklist = None
    if include_welcome:
        welcome = build_welcome_message(employee, tasks)
        checklist = build_checklist_payload(employee, tasks)
        if is_generic_opener(query):
            answer = welcome
        else:
            answer = welcome + "\n\n" + answer
    rag["answer"] = answer
    rag["model_used"] = rag.get("model_used") or "onboarding_rag"
    rag["sub_intent"] = "ask_question"
    if checklist:
        rag["onboarding_checklist"] = checklist
    return rag


def _onboarding_result(
    answer: str,
    *,
    sub_intent: str,
    onboarding_checklist: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "answer": answer,
        "department": "hr",
        "severity": "routine",
        "sources": [],
        "model_used": "onboarding_agent",
        "context_used": False,
        "token_usage": {},
        "node_timings": {},
        "sub_intent": sub_intent,
        "escalated": False,
        "ticket_id": None,
        "attempted_depts": [],
        "retry_count": 0,
    }
    if onboarding_checklist:
        payload["onboarding_checklist"] = onboarding_checklist
    return payload
