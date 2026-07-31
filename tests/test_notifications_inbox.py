"""In-app ticket notification inbox."""

from __future__ import annotations

from app.tickets.inbox import (
    list_notifications,
    mark_all_read,
    mark_read,
    push_ticket_notification,
    unread_count,
)


def test_push_and_unread(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    from app.config import get_settings

    get_settings.cache_clear()

    note = push_ticket_notification(
        {
            "id": "t-1",
            "ticket_type": "unknown",
            "severity": "routine",
            "question": "How do I reset my badge?",
            "department": "unknown",
            "created_by_email": "emp@ampcus.com",
        }
    )
    assert note["kind"] == "ticket_created"
    assert unread_count() == 1
    items = list_notifications()
    assert len(items) == 1
    assert items[0]["ticket_id"] == "t-1"

    marked = mark_read(note["id"])
    assert marked and marked["read_at"]
    assert unread_count() == 0

    push_ticket_notification(
        {
            "id": "t-2",
            "ticket_type": "escalation",
            "severity": "high",
            "question": "Possible data breach report",
            "department": "compliance",
            "created_by_email": "emp@ampcus.com",
        }
    )
    assert unread_count() == 1
    assert mark_all_read() == 1
    assert unread_count() == 0

    get_settings.cache_clear()
