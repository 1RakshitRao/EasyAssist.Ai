"""Daily onboarding reminder job — no LLM."""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Optional

from app.audit.emailer import send_email
from app.config import get_settings
from app.onboarding import store
from app.onboarding.reminder_templates import (
    build_daily_reminder_email,
    build_escalation_email,
    build_manager_alert_email,
)

logger = logging.getLogger(__name__)


def run_onboarding_reminders_once(*, now: Optional[datetime] = None) -> int:
    """
    Send daily onboarding reminders for employees in their 7-day window.
    Idempotent per employee per reminder_type per calendar day.
    Returns number of emails sent.
    """
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    today = now.date()
    window = int(settings.onboarding_window_days or 7)
    hr_email = (settings.onboarding_hr_email or settings.admin_email or "").strip()
    sent_count = 0

    employees = store.list_active_onboarding_employees(today=today, window_days=window)
    for emp in employees:
        email = emp["email"]
        tasks = store.get_tasks(email)
        pending = [t for t in tasks if t.get("status") == "pending"]
        if not pending:
            continue

        day = store.onboarding_day(emp["joining_date"], today)
        if day < 1 or day > window:
            continue

        sent_at = now.isoformat()

        # Employee daily reminder (days 1-7)
        reminder_type = "daily_urgent" if day >= 6 else "daily"
        if not store.has_reminder_today(email, reminder_type, today=today):
            mail = build_daily_reminder_email(
                emp,
                pending,
                onboarding_day=day,
                urgent=day >= 6,
            )
            if send_email(to=email, subject=mail["subject"], body=mail["body"]):
                store.insert_reminder(
                    employee_email=email,
                    reminder_type=reminder_type,
                    sent_at=sent_at,
                )
                store.increment_task_reminders(email, reminded_at=sent_at)
                sent_count += 1
            else:
                store.insert_reminder(
                    employee_email=email,
                    reminder_type=reminder_type,
                    delivery_status="failed",
                    sent_at=sent_at,
                )

        # Manager alert days 6-7
        manager = (emp.get("manager_email") or "").strip()
        if day >= 6 and manager:
            mgr_type = "manager_alert"
            if not store.has_reminder_today(email, mgr_type, today=today):
                mail = build_manager_alert_email(
                    emp, pending, onboarding_day=day
                )
                if send_email(to=manager, subject=mail["subject"], body=mail["body"]):
                    store.insert_reminder(
                        employee_email=email,
                        reminder_type=mgr_type,
                        sent_at=sent_at,
                    )
                    sent_count += 1

        # HR escalation on day 7 if still incomplete
        if day >= window and hr_email:
            esc_type = "escalation"
            if not store.has_reminder_today(email, esc_type, today=today):
                mail = build_escalation_email(emp, pending)
                if send_email(to=hr_email, subject=mail["subject"], body=mail["body"]):
                    store.insert_reminder(
                        employee_email=email,
                        reminder_type=esc_type,
                        sent_at=sent_at,
                    )
                    sent_count += 1

    if sent_count:
        logger.info("Onboarding reminders sent: %s", sent_count)
    return sent_count
