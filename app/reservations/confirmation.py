"""Confirmation numbers and reservation summary formatting."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List


def format_date(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
        return d.strftime("%a %b %d, %Y")
    except ValueError:
        return iso


def nights(checkin: str, checkout: str) -> int:
    try:
        return (date.fromisoformat(checkout) - date.fromisoformat(checkin)).days
    except ValueError:
        return 0


def format_reservation_summary(res: Dict[str, Any]) -> str:
    n = nights(res.get("checkin_date", ""), res.get("checkout_date", ""))
    status = (res.get("status") or "").replace("_", " ").upper()
    lines = [
        f"{res.get('confirmation_number', '—')} · {status}",
        f"{res.get('guesthouse_name', 'Guesthouse')} — Room {res.get('room_number', '?')} "
        f"({res.get('room_name', '')})",
        f"{format_date(res.get('checkin_date', ''))} – {format_date(res.get('checkout_date', ''))}"
        f" · {n} night{'s' if n != 1 else ''}",
    ]
    if res.get("purpose"):
        lines.append(f"Purpose: {res['purpose']}")
    return "\n".join(lines)


def format_availability_grid(
    guesthouse_name: str,
    rooms_calendar: Dict[str, List[dict]],
    room_meta: Dict[str, dict],
) -> str:
    """Format day-by-day availability per room."""
    lines = [f"Availability at {guesthouse_name}:", ""]
    for room_id, days in rooms_calendar.items():
        meta = room_meta.get(room_id, {})
        title = f"Room {meta.get('room_number', '?')} — {meta.get('room_name', 'Room')}"
        lines.append(title)
        for day in days:
            mark = "Available" if day.get("status") == "available" else "Booked"
            if day.get("status") in ("maintenance", "blocked"):
                mark = day["status"].title()
            lines.append(f"  {format_date(day['date'])}  {mark}")
        lines.append("")
    return "\n".join(lines).strip()
