"""Email and chat templates for onboarding."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

CATEGORY_LABELS = {
    "identity": "Identity & Security",
    "payroll": "Payroll",
    "documents": "Documents",
    "benefits": "Benefits",
    "apps": "Apps & Tools",
}

CATEGORY_EMOJI = {
    "identity": "📋",
    "payroll": "💰",
    "documents": "📄",
    "benefits": "🏥",
    "apps": "💻",
}

TIP_CATEGORY_ORDER = ["identity", "payroll", "documents", "benefits", "apps"]


def _format_join_date(joining_date: str) -> str:
    try:
        d = datetime.strptime(joining_date[:10], "%Y-%m-%d")
        return f"{d.strftime('%B')} {d.day}"
    except ValueError:
        return joining_date


def _progress_bar(completed: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "░" * width
    filled = round(width * completed / total)
    return "▓" * filled + "░" * (width - filled)


def _next_tip_task(tasks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    pending = [t for t in tasks if t.get("status") == "pending"]
    for cat in TIP_CATEGORY_ORDER:
        for t in sorted(pending, key=lambda x: int(x.get("sort_order") or 0)):
            if t.get("category") == cat:
                return t
    return pending[0] if pending else None


def _task_payload(task: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": task.get("id"),
        "task_key": task.get("task_key"),
        "task_title": task.get("task_title"),
        "category": task.get("category") or "other",
        "status": task.get("status") or "pending",
        "link_url": task.get("link_url"),
        "due_date": task.get("due_date"),
    }


def build_checklist_payload(
    employee: Dict[str, Any],
    tasks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Structured checklist for the interactive chat glass UI."""
    completed = [t for t in tasks if t.get("status") == "completed"]
    pending = [t for t in tasks if t.get("status") == "pending"]
    total = len(tasks)
    done_count = len(completed)
    pct = round(100 * done_count / total) if total else 0

    by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for t in pending:
        by_cat.setdefault(t.get("category") or "other", []).append(_task_payload(t))

    pending_by_category: Dict[str, List[Dict[str, Any]]] = {}
    for cat in TIP_CATEGORY_ORDER:
        if cat in by_cat:
            pending_by_category[cat] = by_cat[cat]
    for cat, items in by_cat.items():
        if cat not in pending_by_category:
            pending_by_category[cat] = items

    tip = _next_tip_task(tasks)
    tip_text = None
    if tip:
        tip_text = (
            f"Start with {tip['task_title']} — it unlocks access to most other systems."
        )

    first_name = (employee.get("full_name") or "").split()[0] or None
    return {
        "title": "Your Onboarding Progress",
        "completed": done_count,
        "total": total,
        "percentage": pct,
        "done": [_task_payload(t) for t in completed],
        "pending_by_category": pending_by_category,
        "category_labels": {
            cat: CATEGORY_LABELS.get(cat, cat.replace("_", " ").title())
            for cat in pending_by_category
        },
        "tip": tip_text,
        "employee_name": first_name,
    }


def build_checklist_response(
    employee: Dict[str, Any],
    tasks: List[Dict[str, Any]],
    *,
    company_name: str = "Ampcus",
) -> str:
    completed = [t for t in tasks if t.get("status") == "completed"]
    pending = [t for t in tasks if t.get("status") == "pending"]
    total = len(tasks)
    done_count = len(completed)

    lines = [
        f"Your Onboarding Progress",
        f"{_progress_bar(done_count, total)} {done_count} of {total} tasks complete",
        "",
    ]

    if completed:
        lines.append("✅ DONE")
        for t in completed:
            lines.append(f"  • {t['task_title']}")
        lines.append("")

    if pending:
        lines.append(f"⏳ PENDING ({len(pending)})")
        by_cat: Dict[str, List[Dict[str, Any]]] = {}
        for t in pending:
            by_cat.setdefault(t.get("category") or "other", []).append(t)
        for cat in TIP_CATEGORY_ORDER:
            if cat not in by_cat:
                continue
            lines.append(f"  {CATEGORY_LABELS.get(cat, cat.title())}")
            for t in by_cat[cat]:
                link = f" → {t['link_url']}" if t.get("link_url") else ""
                lines.append(f"  • [ ] {t['task_title']}{link}")
        lines.append("")

    tip = _next_tip_task(tasks)
    if tip:
        lines.append(
            f"💡 Start with {tip['task_title']} — it unlocks access to most other systems."
        )

    return "\n".join(lines)


def build_welcome_message(
    employee: Dict[str, Any],
    tasks: List[Dict[str, Any]],
    *,
    company_name: str = "Ampcus Corporation",
) -> str:
    name = employee.get("full_name", "").split()[0] or "there"
    joined = _format_join_date(employee.get("joining_date", ""))
    checklist = build_checklist_response(employee, tasks, company_name=company_name)
    return (
        f"Welcome to {company_name}, {name}! 🎉\n\n"
        f"You joined on {joined}. Here's where you stand:\n\n"
        f"━━━ Your Onboarding Progress ━━━\n"
        f"{checklist}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f'Ask me anything: "What documents do I need for I-9?" or "How do I set up VPN?"'
    )


def build_daily_reminder_email(
    employee: Dict[str, Any],
    pending_tasks: List[Dict[str, Any]],
    *,
    onboarding_day: int,
    company_name: str = "Ampcus Corporation",
    urgent: bool = False,
) -> Dict[str, str]:
    name = employee.get("full_name", "").split()[0] or "there"
    count = len(pending_tasks)
    subject_prefix = "URGENT: " if urgent else ""
    subject = f"{subject_prefix}Action needed — {count} onboarding task{'s' if count != 1 else ''} remaining"

    lines = [
        f"Hi {name},",
        "",
        f"You're on Day {onboarding_day} of your onboarding at {company_name}.",
        f"You still have {count} task{'s' if count != 1 else ''} to complete:",
        "",
    ]
    for t in pending_tasks:
        emoji = CATEGORY_EMOJI.get(t.get("category") or "", "📋")
        desc = t.get("task_description") or t.get("task_title")
        link = t.get("link_url") or ""
        link_line = f" → {link}" if link else ""
        lines.append(f"  {emoji} {t['task_title']}")
        lines.append(f"     {desc}{link_line}")
        lines.append("")

    lines.extend(
        [
            "Questions? Just ask the helpdesk chatbot.",
            "",
            "— HR Team",
        ]
    )
    body = "\n".join(lines)
    return {"subject": subject, "body": body}


def build_manager_alert_email(
    employee: Dict[str, Any],
    pending_tasks: List[Dict[str, Any]],
    *,
    onboarding_day: int,
    company_name: str = "Ampcus Corporation",
) -> Dict[str, str]:
    name = employee.get("full_name", "Employee")
    subject = f"Onboarding follow-up needed — {name} (Day {onboarding_day})"
    pending_lines = "\n".join(f"  • {t['task_title']}" for t in pending_tasks) or "  • (none)"
    body = (
        f"Hi,\n\n"
        f"{name} joined on {employee.get('joining_date')} and is on Day {onboarding_day} "
        f"of onboarding at {company_name}.\n\n"
        f"Incomplete tasks:\n{pending_lines}\n\n"
        f"Employee email: {employee.get('email')}\n\n"
        f"Please encourage them to complete remaining items.\n"
    )
    return {"subject": subject, "body": body}


def build_escalation_email(
    employee: Dict[str, Any],
    pending_tasks: List[Dict[str, Any]],
    *,
    company_name: str = "Ampcus Corporation",
) -> Dict[str, str]:
    name = employee.get("full_name", "Employee")
    dept = employee.get("department", "").title()
    subject = f"⚠ Onboarding incomplete — {name} ({dept})"
    pending_lines = "\n".join(f"  • {t['task_title']}" for t in pending_tasks)
    manager = employee.get("manager_email") or "N/A"
    body = (
        f"{name} joined on {employee.get('joining_date')} and has not completed onboarding:\n\n"
        f"{pending_lines}\n\n"
        f"Please follow up directly.\n"
        f"Employee email: {employee.get('email')}\n"
        f"Manager: {manager}\n"
    )
    return {"subject": subject, "body": body}
