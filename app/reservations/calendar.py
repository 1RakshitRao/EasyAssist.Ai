"""Interactive guesthouse calendar payload for chat UI."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from app.reservations import store

STATUS_AVAILABLE = "available"
STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"


def _date_range(from_d: date, to_d: date) -> List[str]:
    days: List[str] = []
    current = from_d
    while current <= to_d:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def day_display_status(room_id: str, day: str) -> str:
    """Map DB state to calendar color: available | pending | confirmed."""
    rows = store.get_room_availability_calendar(room_id, day, day)
    entry = rows[0] if rows else {"status": store.AVAIL_AVAILABLE}
    status = entry.get("status") or store.AVAIL_AVAILABLE
    reservation_id = entry.get("reservation_id")

    if reservation_id:
        res = store.get_reservation(reservation_id)
        if res:
            res_status = (res.get("status") or "").lower()
            if res_status == store.STATUS_PENDING:
                return STATUS_PENDING
            if res_status in (
                store.STATUS_CONFIRMED,
                store.STATUS_OVERRIDDEN,
                store.STATUS_COMPLETED,
            ):
                return STATUS_CONFIRMED

    if status in (
        store.AVAIL_BOOKED,
        store.AVAIL_MAINTENANCE,
        store.AVAIL_BLOCKED,
    ):
        return STATUS_CONFIRMED
    return STATUS_AVAILABLE


def build_calendar_payload(
    *,
    guesthouse_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    weeks: int = 6,
) -> Dict[str, Any]:
    """Build calendar widget data for one guesthouse (all rooms)."""
    gh = store.get_guesthouse_with_rooms(guesthouse_id)
    if not gh:
        raise ValueError("Guesthouse not found")

    start = date.fromisoformat(from_date) if from_date else date.today() + timedelta(days=1)
    end = date.fromisoformat(to_date) if to_date else start + timedelta(days=weeks * 7 - 1)
    if end < start:
        end = start + timedelta(days=weeks * 7 - 1)

    dates = _date_range(start, end)
    rooms_payload: List[dict] = []
    for room in gh.get("rooms", []):
        rid = room["id"]
        days = [{"date": d, "status": day_display_status(rid, d)} for d in dates]
        rooms_payload.append(
            {
                "room_id": rid,
                "room_number": room.get("room_number"),
                "room_name": room.get("room_name"),
                "days": days,
            }
        )

    return {
        "guesthouse_id": gh["id"],
        "guesthouse_name": gh["name"],
        "display_name": store.guesthouse_display_name(gh["id"]),
        "from_date": start.isoformat(),
        "to_date": end.isoformat(),
        "display_month": start.strftime("%Y-%m"),
        "rooms": rooms_payload,
        "purposes": list(store.VISIT_PURPOSES),
        "legend": {
            STATUS_AVAILABLE: "Available",
            STATUS_PENDING: "Awaiting confirmation",
            STATUS_CONFIRMED: "Confirmed / unavailable",
        },
    }


def build_admin_calendar_payload(
    *,
    guesthouse_id: str,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    weeks: int = 6,
) -> Dict[str, Any]:
    """Calendar widget data with reservation details for HR admin."""
    gh = store.get_guesthouse_with_rooms(guesthouse_id)
    if not gh:
        raise ValueError("Guesthouse not found")

    start = date.fromisoformat(from_date) if from_date else date.today()
    end = date.fromisoformat(to_date) if to_date else start + timedelta(days=weeks * 7 - 1)
    if end < start:
        end = start + timedelta(days=weeks * 7 - 1)

    dates = _date_range(start, end)
    rooms_payload: List[dict] = []
    for room in gh.get("rooms", []):
        rid = room["id"]
        cal_rows = store.get_room_availability_calendar(
            rid, start.isoformat(), end.isoformat()
        )
        cal_map = {r["date"]: r for r in cal_rows}
        days: List[dict] = []
        for d in dates:
            entry = cal_map.get(d, {})
            status = day_display_status(rid, d)
            day_obj: Dict[str, Any] = {"date": d, "status": status}
            res_id = entry.get("reservation_id")
            if res_id:
                res = store.get_reservation(res_id)
                if res:
                    day_obj["reservation_id"] = res_id
                    day_obj["employee_email"] = res.get("employee_email")
                    day_obj["confirmation_number"] = res.get("confirmation_number")
                    day_obj["reservation_status"] = res.get("status")
                    day_obj["checkin_date"] = res.get("checkin_date")
                    day_obj["checkout_date"] = res.get("checkout_date")
            days.append(day_obj)
        rooms_payload.append(
            {
                "room_id": rid,
                "room_number": room.get("room_number"),
                "room_name": room.get("room_name"),
                "days": days,
            }
        )

    return {
        "guesthouse_id": gh["id"],
        "guesthouse_name": gh["name"],
        "display_name": store.guesthouse_display_name(gh["id"]),
        "from_date": start.isoformat(),
        "to_date": end.isoformat(),
        "display_month": start.strftime("%Y-%m"),
        "rooms": rooms_payload,
        "purposes": list(store.VISIT_PURPOSES),
        "legend": {
            STATUS_AVAILABLE: "Available",
            STATUS_PENDING: "Awaiting confirmation",
            STATUS_CONFIRMED: "Confirmed / unavailable",
        },
    }
