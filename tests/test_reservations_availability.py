"""Tests for Excel availability upload and conflict detection."""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from openpyxl import Workbook

from app.config import get_settings
from app.reservations import availability as avail_mod
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


def _future(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _excel_bytes(rows: list[tuple]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(
        ("guesthouse_name", "room_number", "date_from", "date_until", "status")
    )
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_excel_rows(reservation_db):
    gh = store.get_all_guesthouses()[0]
    day = _future(15)
    data = _excel_bytes([(gh["name"], "1", day, day, "maintenance")])
    rows = avail_mod.parse_excel_rows(data)
    assert len(rows) == 1
    assert rows[0]["status"] == "maintenance"


def test_upload_applies_available(reservation_db):
    gh = store.get_all_guesthouses()[0]
    day = _future(16)
    data = _excel_bytes([(gh["name"], "1", day, day, "maintenance")])
    result = avail_mod.process_excel_upload(data, "admin@ampcus.com")
    assert result["applied"] == 1
    assert not result["conflicts"]


def test_upload_conflict_with_booking(reservation_db):
    room = store.get_all_rooms()[0]
    checkin = _future(20)
    checkout = _future(23)
    store.create_reservation("emp@ampcus.com", room["id"], checkin, checkout, "Training")
    gh_name = room["guesthouse_name"]
    day = _future(21)
    data = _excel_bytes([(gh_name, room["room_number"], day, day, "maintenance")])
    result = avail_mod.process_excel_upload(data, "admin@ampcus.com")
    assert result["applied"] == 0
    assert len(result["conflicts"]) == 1


def test_resolve_skip(reservation_db):
    result = avail_mod.resolve_conflicts(
        [
            {
                "room_id": "x",
                "date": "2026-01-01",
                "proposed_status": "maintenance",
                "action": "skip",
            }
        ],
        "admin@ampcus.com",
    )
    assert result["skipped"] == 1
