"""Board monitor agent — watches escalation Kanban stories for SLA breaches.

MVP: monitors local escalation tickets (Jira-like board). Future: same agent
will watch a real Jira board (see docs/future-jira-integration.md).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.tickets.notify import process_escalation_reminders
from app.tickets.store import TICKET_TYPE_ESCALATION, list_due_escalation_reminders, list_tickets

logger = logging.getLogger(__name__)


class BoardMonitorAgent:
    """
    Separate agent responsible for escalation-board SLA notifications.

    If a story (escalation ticket) is not resolved within the configured
    window, send one admin reminder email.
    """

    def __init__(self) -> None:
        self.last_run_at: Optional[str] = None
        self.last_reminded: int = 0

    def list_board_stories(self) -> List[Dict[str, Any]]:
        """All escalation tickets shown on the MVP Jira-like board."""
        return list_tickets(ticket_type=TICKET_TYPE_ESCALATION)

    def unresolved_past_sla(
        self, *, now: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        settings = get_settings()
        return list_due_escalation_reminders(
            now=now, hours=float(settings.escalation_reminder_hours)
        )

    def run_once(self, *, now: Optional[datetime] = None) -> int:
        """
        Scan the board and notify admins for due unresolved stories.
        Returns number of reminders sent.
        """
        due = self.unresolved_past_sla(now=now)
        if due:
            logger.info(
                "BoardMonitorAgent: %s story(ies) past SLA (not resolved)",
                len(due),
            )
        sent = process_escalation_reminders(now=now)
        self.last_run_at = datetime.now(timezone.utc).isoformat()
        self.last_reminded = sent
        if sent:
            logger.info("BoardMonitorAgent: sent %s admin reminder(s)", sent)
        return sent


_agent: Optional[BoardMonitorAgent] = None


def get_board_monitor() -> BoardMonitorAgent:
    global _agent
    if _agent is None:
        _agent = BoardMonitorAgent()
    return _agent


def run_board_monitor_once(*, now: Optional[datetime] = None) -> int:
    return get_board_monitor().run_once(now=now)
