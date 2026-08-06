"""Reservation API integration tests."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.config import get_settings
from app.reservations import store


@pytest.fixture()
def seeded_client(client):
    get_settings.cache_clear()
    store.seed_guesthouses()
    return client


def _future(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def test_book_approve_flow(seeded_client, employee_headers, admin_headers):
    rooms = store.get_all_rooms()
    room_id = rooms[0]["id"]
    checkin = _future(90)
    checkout = _future(93)

    with patch("app.api.routes_reservations.fire_create_notifications"):
        create = seeded_client.post(
            "/reservations",
            headers=employee_headers,
            json={
                "room_id": room_id,
                "checkin_date": checkin,
                "checkout_date": checkout,
                "purpose": "Business travel",
            },
        )
    assert create.status_code == 201, create.text
    body = create.json()
    rid = body["id"]

    pending = seeded_client.get("/admin/reservations/pending", headers=admin_headers)
    assert pending.status_code == 200
    assert any(p["id"] == rid for p in pending.json())

    with patch("app.api.routes_reservations.fire_approve_notification"):
        approved = seeded_client.post(
            f"/admin/reservations/{rid}/approve",
            headers=admin_headers,
        )
    assert approved.status_code == 200
    assert approved.json()["status"] == "confirmed"

    mine = seeded_client.get("/reservations/my", headers=employee_headers)
    assert mine.status_code == 200
    assert any(r["id"] == rid for r in mine.json())


def test_my_reservations_empty(seeded_client, employee_headers):
    res = seeded_client.get("/reservations/my", headers=employee_headers)
    assert res.status_code == 200
    assert isinstance(res.json(), list)
