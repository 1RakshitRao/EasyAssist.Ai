"""Daily guesthouse reservation reminders and auto-approve."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.reservations import store
from app.reservations.notifications import (
    fire_approve_notification,
    notify_48h_reminder,
    notify_checkin_day,
    notify_checkout_day,
)

logger = logging.getLogger(__name__)


def run_reservation_reminders_once(*, now: Optional[datetime] = None) -> int:
    """
    Auto-approve pending reservations past SLA, send reminder emails,
    mark completed stays. Returns count of actions taken.
    """
    now = now or datetime.now(timezone.utc)
    actions = 0

    for res in store.get_reservations_due_auto_approve():
        try:
            approved = store.approve_reservation(res["id"], "system-auto-approve")
            fire_approve_notification(approved)
            actions += 1
            logger.info("Auto-approved reservation %s", approved.get("confirmation_number"))
        except Exception:
            logger.exception("Auto-approve failed for %s", res.get("id"))

    reminders = store.get_reservations_needing_reminders()
    for res in reminders.get("remind_48h", []):
        if notify_48h_reminder(res):
            store.mark_notified(res["id"], "48h")
            actions += 1

    for res in reminders.get("remind_checkin", []):
        if notify_checkin_day(res):
            store.mark_notified(res["id"], "checkin")
            actions += 1

    for res in reminders.get("remind_checkout", []):
        if notify_checkout_day(res):
            store.mark_notified(res["id"], "checkout")
            actions += 1

    completed = store.mark_completed_reservations()
    if completed:
        actions += completed
        logger.info("Marked %s reservations completed", completed)

    if actions:
        logger.info("Reservation reminder job actions: %s", actions)
    return actions
