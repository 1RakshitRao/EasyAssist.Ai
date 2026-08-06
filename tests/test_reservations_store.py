"""Unit tests for guesthouse reservation store."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.reservations import store


@pytest.fixture()
def reservation_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    get_settings.cache_clear()
    from app.audit.db import init_audit_db

    init_audit_db()
    store.seed_guesthouses()
    yield
    get_settings.cache_clear()


def _future(days_ahead: int = 10) -> str:
    return (date.today() + timedelta(days=days_ahead)).isoformat()


def _room_id() -> str:
    rooms = store.get_all_rooms()
    assert rooms
    return rooms[0]["id"]


def test_seed_guesthouses(reservation_db):
    houses = store.get_all_guesthouses()
    assert len(houses) == 2
    assert store.get_all_rooms().__len__() == 4


def test_create_reservation(reservation_db):
    room_id = _room_id()
    checkin = _future(10)
    checkout = _future(13)
    res = store.create_reservation(
        "emp@ampcus.com", room_id, checkin, checkout, "Business travel"
    )
    assert res["status"] == store.STATUS_PENDING
    assert res["confirmation_number"].startswith("GH-")
    assert res["auto_approve_at"]


def test_create_rejects_past_checkin(reservation_db):
    room_id = _room_id()
    with pytest.raises(ValueError, match="future"):
        store.create_reservation(
            "emp@ampcus.com",
            room_id,
            date.today().isoformat(),
            _future(2),
            "Business travel",
        )


def test_create_rejects_unavailable(reservation_db):
    room_id = _room_id()
    checkin = _future(10)
    checkout = _future(13)
    store.create_reservation("a@ampcus.com", room_id, checkin, checkout, "Training")
    with pytest.raises(ValueError, match="not available"):
        store.create_reservation("b@ampcus.com", room_id, checkin, checkout, "Training")


def test_approve_reservation(reservation_db):
    room_id = _room_id()
    res = store.create_reservation(
        "emp@ampcus.com", _room_id(), _future(20), _future(23), "Other"
    )
    approved = store.approve_reservation(res["id"], "hr@ampcus.com")
    assert approved["status"] == store.STATUS_CONFIRMED
    assert approved["approved_by"] == "hr@ampcus.com"


def test_reject_frees_dates(reservation_db):
    room_id = _room_id()
    checkin = _future(30)
    checkout = _future(33)
    res = store.create_reservation("emp@ampcus.com", room_id, checkin, checkout, "Training")
    store.reject_reservation(res["id"], "hr@ampcus.com", "No capacity")
    avail = store.get_availability(checkin, checkout)
    room_avail = next(r for r in avail if r["room_id"] == room_id)
    assert room_avail["available"] is True


def test_cancel_pending(reservation_db):
    res = store.create_reservation(
        "emp@ampcus.com", _room_id(), _future(40), _future(42), "Business travel"
    )
    cancelled = store.cancel_reservation(res["id"], "emp@ampcus.com")
    assert cancelled["status"] == store.STATUS_CANCELLED


def test_can_modify_48h_block(reservation_db):
    checkin = (date.today() + timedelta(days=1)).isoformat()
    checkout = (date.today() + timedelta(days=3)).isoformat()
    res = store.create_reservation("emp@ampcus.com", _room_id(), checkin, checkout, "Other")
    store.approve_reservation(res["id"], "hr@ampcus.com")
    updated = store.get_reservation(res["id"])
    ok, msg = store.can_modify(updated)
    assert ok is False
    assert "48 hours" in msg


def test_modify_reservation(reservation_db):
    res = store.create_reservation(
        "emp@ampcus.com", _room_id(), _future(50), _future(52), "Client meeting"
    )
    store.approve_reservation(res["id"], "hr@ampcus.com")
    modified = store.modify_reservation(
        res["id"], "emp@ampcus.com", _future(55), _future(58)
    )
    assert modified["status"] == store.STATUS_PENDING
    assert modified["checkin_date"] == _future(55)


def test_override_reservation(reservation_db):
    res = store.create_reservation(
        "emp@ampcus.com", _room_id(), _future(60), _future(62), "Team offsite"
    )
    store.approve_reservation(res["id"], "hr@ampcus.com")
    overridden = store.override_reservation(res["id"], "hr@ampcus.com", "Maintenance")
    assert overridden["status"] == store.STATUS_OVERRIDDEN


def test_auto_approve_due_query(reservation_db):
    res = store.create_reservation(
        "emp@ampcus.com", _room_id(), _future(70), _future(72), "Business travel"
    )
    from app.audit.db import connect

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with connect() as conn:
        conn.execute(
            "UPDATE reservations SET auto_approve_at = ? WHERE id = ?",
            (past, res["id"]),
        )
        conn.commit()
    due = store.get_reservations_due_auto_approve()
    assert any(r["id"] == res["id"] for r in due)


def test_occupancy_report(reservation_db):
    store.create_reservation(
        "emp@ampcus.com", _room_id(), _future(80), _future(82), "Business travel"
    )
    report = store.get_occupancy_report(_future(79), _future(83))
    assert "occupancy_pct" in report
