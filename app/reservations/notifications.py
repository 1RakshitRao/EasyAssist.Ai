"""Guesthouse reservation email notifications."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.audit.emailer import send_email
from app.config import get_settings
from app.reservations import store
from app.reservations.confirmation import format_date, format_reservation_summary, nights
from app.tickets.notify import admin_recipient_emails, app_base_url

logger = logging.getLogger(__name__)


def _hr_recipients() -> List[str]:
    settings = get_settings()
    hr = (settings.reservation_hr_email or settings.onboarding_hr_email or "").strip().lower()
    if hr:
        return [hr]
    return admin_recipient_emails()


def _employee_email(res: dict) -> str:
    return str(res.get("employee_email") or "").strip().lower()


def notify_submitted(res: dict) -> bool:
    """Employee: reservation submitted."""
    email = _employee_email(res)
    if not email:
        return False
    body = "\n".join(
        [
            "Your guesthouse reservation request has been submitted.",
            "",
            format_reservation_summary(res),
            "",
            "HR will review your request. You will receive another email once it is confirmed.",
            f"Manage bookings: {app_base_url()}/",
            "",
            "— Ampcus Helpdesk",
        ]
    )
    return send_email(
        to=email,
        subject=f"[Ampcus] Guesthouse request submitted — {res.get('confirmation_number', '')}",
        body=body,
    )


def notify_hr_approval_needed(res: dict) -> bool:
    """HR: new pending reservation."""
    recipients = _hr_recipients()
    if not recipients:
        return False
    body = "\n".join(
        [
            "A guesthouse reservation needs HR approval.",
            "",
            format_reservation_summary(res),
            "",
            f"Review in Ampcus Helpdesk: {app_base_url()}/",
            "",
            "— Ampcus Helpdesk",
        ]
    )
    ok = False
    for addr in recipients:
        if send_email(
            to=addr,
            subject=f"[Ampcus] Approve guesthouse — {res.get('confirmation_number', '')}",
            body=body,
        ):
            ok = True
    return ok


def notify_confirmed(res: dict) -> bool:
    email = _employee_email(res)
    if not email:
        return False
    n = nights(res.get("checkin_date", ""), res.get("checkout_date", ""))
    body = "\n".join(
        [
            "Your guesthouse reservation is confirmed.",
            "",
            format_reservation_summary(res),
            "",
            f"Check-in: {format_date(res.get('checkin_date', ''))}",
            f"Check-out: {format_date(res.get('checkout_date', ''))} ({n} night{'s' if n != 1 else ''})",
            "",
            f"View details: {app_base_url()}/",
            "",
            "— Ampcus Helpdesk",
        ]
    )
    return send_email(
        to=email,
        subject=f"[Ampcus] Guesthouse confirmed — {res.get('confirmation_number', '')}",
        body=body,
    )


def notify_rejected(res: dict, reason: str) -> bool:
    email = _employee_email(res)
    if not email:
        return False
    body = "\n".join(
        [
            "Your guesthouse reservation request was not approved.",
            "",
            format_reservation_summary(res),
            "",
            f"Reason: {reason or 'Not specified'}",
            "",
            "Contact HR if you have questions.",
            "",
            "— Ampcus Helpdesk",
        ]
    )
    return send_email(
        to=email,
        subject=f"[Ampcus] Guesthouse request declined — {res.get('confirmation_number', '')}",
        body=body,
    )


def notify_overridden(res: dict, reason: str) -> bool:
    email = _employee_email(res)
    if not email:
        return False
    body = "\n".join(
        [
            "Your guesthouse reservation was overridden by HR.",
            "",
            format_reservation_summary(res),
            "",
            f"Reason: {reason or 'Not specified'}",
            "",
            f"Contact HR at {store.hr_contact_email()} if you need assistance.",
            "",
            "— Ampcus Helpdesk",
        ]
    )
    return send_email(
        to=email,
        subject=f"[Ampcus] Guesthouse reservation overridden — {res.get('confirmation_number', '')}",
        body=body,
    )


def notify_cancelled(res: dict) -> bool:
    email = _employee_email(res)
    if not email:
        return False
    body = "\n".join(
        [
            "Your guesthouse reservation has been cancelled.",
            "",
            format_reservation_summary(res),
            "",
            "— Ampcus Helpdesk",
        ]
    )
    return send_email(
        to=email,
        subject=f"[Ampcus] Guesthouse cancelled — {res.get('confirmation_number', '')}",
        body=body,
    )


def notify_48h_reminder(res: dict) -> bool:
    email = _employee_email(res)
    if not email:
        return False
    body = "\n".join(
        [
            "Reminder: your guesthouse check-in is in 48 hours.",
            "",
            format_reservation_summary(res),
            "",
            "— Ampcus Helpdesk",
        ]
    )
    return send_email(
        to=email,
        subject=f"[Ampcus] Guesthouse check-in in 48h — {res.get('confirmation_number', '')}",
        body=body,
    )


def notify_checkin_day(res: dict) -> bool:
    email = _employee_email(res)
    if not email:
        return False
    gh = res.get("guesthouse_name") or "Guesthouse"
    addr = res.get("guesthouse_address") or ""
    body = "\n".join(
        [
            f"Today is your check-in day at {gh}.",
            "",
            format_reservation_summary(res),
            "",
            f"Address: {addr}" if addr else "",
            "",
            "— Ampcus Helpdesk",
        ]
    )
    return send_email(
        to=email,
        subject=f"[Ampcus] Guesthouse check-in today — {res.get('confirmation_number', '')}",
        body=body,
    )


def notify_checkout_day(res: dict) -> bool:
    email = _employee_email(res)
    if not email:
        return False
    body = "\n".join(
        [
            "Today is your check-out day.",
            "",
            format_reservation_summary(res),
            "",
            "Please leave the room tidy and report any issues to HR.",
            "",
            "— Ampcus Helpdesk",
        ]
    )
    return send_email(
        to=email,
        subject=f"[Ampcus] Guesthouse check-out today — {res.get('confirmation_number', '')}",
        body=body,
    )


def notify_excel_conflicts(conflicts: List[dict]) -> bool:
    recipients = _hr_recipients()
    if not recipients or not conflicts:
        return False
    lines = ["Excel availability upload encountered conflicts:", ""]
    for c in conflicts[:50]:
        lines.append(
            f"- {c.get('guesthouse_name')} Room {c.get('room_number')} "
            f"{c.get('date')}: {c.get('confirmation_number') or c.get('reason', 'conflict')}"
        )
    if len(conflicts) > 50:
        lines.append(f"... and {len(conflicts) - 50} more")
    lines.extend(["", f"Resolve in Ampcus Helpdesk: {app_base_url()}/", "", "— Ampcus Helpdesk"])
    body = "\n".join(lines)
    ok = False
    for addr in recipients:
        if send_email(to=addr, subject="[Ampcus] Guesthouse availability conflicts", body=body):
            ok = True
    return ok


def fire_create_notifications(res: dict) -> None:
    from app.tickets.inbox import push_reservation_notification

    notify_submitted(res)
    notify_hr_approval_needed(res)
    try:
        push_reservation_notification(res)
    except Exception:
        logger.exception("in-app reservation notification failed")


def fire_approve_notification(res: dict) -> None:
    notify_confirmed(res)


def fire_reject_notification(res: dict, reason: str) -> None:
    notify_rejected(res, reason)


def fire_override_notification(res: dict, reason: str) -> None:
    notify_overridden(res, reason)


def fire_cancel_notification(res: dict) -> None:
    notify_cancelled(res)
