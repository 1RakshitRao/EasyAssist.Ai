"""Microsoft Graph calendar integration for conference room booking."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.config import get_settings
from app.infrastructure import store

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


@dataclass
class GraphConfig:
    tenant_id: str
    client_id: str
    client_secret: str


def _graph_configured() -> bool:
    s = get_settings()
    return bool(
        (s.microsoft_tenant_id or "").strip()
        and (s.microsoft_client_id or "").strip()
        and (s.microsoft_client_secret or "").strip()
    )


def _get_access_token() -> Optional[str]:
    if not _graph_configured():
        return None
    s = get_settings()
    url = f"https://login.microsoftonline.com/{s.microsoft_tenant_id}/oauth2/v2.0/token"
    data = {
        "client_id": s.microsoft_client_id,
        "client_secret": s.microsoft_client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, data=data)
            resp.raise_for_status()
            return resp.json().get("access_token")
    except Exception as exc:
        logger.warning("Graph token fetch failed: %s", exc)
        return None


def _graph_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def list_rooms_from_graph() -> List[Dict[str, Any]]:
    """Fetch room resources from Microsoft Graph Places API."""
    token = _get_access_token()
    if not token:
        return []
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                f"{GRAPH_BASE}/places/microsoft.graph.room",
                headers=_graph_headers(token),
            )
            if resp.status_code != 200:
                logger.warning("Graph list rooms failed status=%s", resp.status_code)
                return []
            items = resp.json().get("value") or []
            rooms = []
            for item in items:
                rooms.append(
                    {
                        "room_name": item.get("displayName") or "",
                        "room_email": item.get("emailAddress") or "",
                        "capacity": item.get("capacity"),
                        "office_location": item.get("building") or "",
                        "floor": item.get("floorNumber"),
                    }
                )
            return rooms
    except Exception as exc:
        logger.warning("Graph list rooms error: %s", exc)
        return []


def get_available_rooms(
    *,
    start: datetime,
    end: datetime,
    min_capacity: int = 1,
    office_location: str | None = None,
) -> List[Dict[str, Any]]:
    """Return rooms free in the given window (Graph schedule or local cache)."""
    settings = get_settings()
    if settings.conference_room_booking_enabled and _graph_configured():
        return _get_available_rooms_graph(
            start=start, end=end, min_capacity=min_capacity, office_location=office_location
        )
    return _get_available_rooms_local(
        start=start, end=end, min_capacity=min_capacity, office_location=office_location
    )


def _get_available_rooms_local(
    *,
    start: datetime,
    end: datetime,
    min_capacity: int,
    office_location: str | None,
) -> List[Dict[str, Any]]:
    rooms = store.list_conference_rooms(office_location=office_location)
    return [r for r in rooms if int(r.get("capacity") or 0) >= min_capacity]


def _get_available_rooms_graph(
    *,
    start: datetime,
    end: datetime,
    min_capacity: int,
    office_location: str | None,
) -> List[Dict[str, Any]]:
    token = _get_access_token()
    if not token:
        return _get_available_rooms_local(
            start=start, end=end, min_capacity=min_capacity, office_location=office_location
        )

    rooms = list_rooms_from_graph()
    if not rooms:
        return _get_available_rooms_local(
            start=start, end=end, min_capacity=min_capacity, office_location=office_location
        )

    if office_location:
        ol = office_location.lower()
        rooms = [r for r in rooms if ol in (r.get("office_location") or "").lower()]

    rooms = [r for r in rooms if int(r.get("capacity") or 0) >= min_capacity]
    if not rooms:
        return []

    emails = [r["room_email"] for r in rooms if r.get("room_email")]
    if not emails:
        return rooms

    schedule_body = {
        "schedules": emails,
        "startTime": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
        "endTime": {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
        "availabilityViewInterval": 30,
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{GRAPH_BASE}/users/{emails[0]}/calendar/getSchedule",
                headers=_graph_headers(token),
                json=schedule_body,
            )
            if resp.status_code != 200:
                return rooms
            schedule_items = resp.json().get("value") or []
            busy_emails = set()
            for item in schedule_items:
                email = item.get("scheduleId") or ""
                for block in item.get("scheduleItems") or []:
                    if block.get("status") in ("busy", "tentative", "oof"):
                        busy_emails.add(email)
            return [r for r in rooms if r.get("room_email") not in busy_emails]
    except Exception as exc:
        logger.warning("Graph getSchedule error: %s", exc)
        return rooms


def create_booking(
    *,
    user_email: str,
    room_email: str,
    room_name: str,
    start: datetime,
    end: datetime,
    title: str = "Meeting",
) -> Dict[str, Any]:
    """Create calendar event with room as location."""
    settings = get_settings()
    if settings.conference_room_booking_enabled and _graph_configured():
        return _create_booking_graph(
            user_email=user_email,
            room_email=room_email,
            room_name=room_name,
            start=start,
            end=end,
            title=title,
        )
    return {
        "success": True,
        "simulated": True,
        "event_id": "local-simulated",
        "message": (
            f"Booked {room_name} for {start.strftime('%Y-%m-%d %H:%M')}–"
            f"{end.strftime('%H:%M')} (simulated — Graph not configured)."
        ),
    }


def _create_booking_graph(
    *,
    user_email: str,
    room_email: str,
    room_name: str,
    start: datetime,
    end: datetime,
    title: str,
) -> Dict[str, Any]:
    token = _get_access_token()
    if not token:
        return {"success": False, "message": "Microsoft Graph authentication failed."}

    event = {
        "subject": title,
        "start": {"dateTime": start.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
        "end": {"dateTime": end.strftime("%Y-%m-%dT%H:%M:%S"), "timeZone": "UTC"},
        "location": {"displayName": room_name, "locationEmailAddress": room_email},
        "attendees": [
            {
                "emailAddress": {"address": room_email, "name": room_name},
                "type": "resource",
            }
        ],
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{GRAPH_BASE}/users/{user_email}/events",
                headers=_graph_headers(token),
                json=event,
            )
            if resp.status_code not in (200, 201):
                return {
                    "success": False,
                    "message": f"Graph create event failed (HTTP {resp.status_code}).",
                }
            data = resp.json()
            return {
                "success": True,
                "simulated": False,
                "event_id": data.get("id"),
                "message": (
                    f"Booked **{room_name}** for {start.strftime('%A %b %d, %H:%M')}–"
                    f"{end.strftime('%H:%M')}. Calendar invite sent."
                ),
            }
    except Exception as exc:
        logger.warning("Graph create event error: %s", exc)
        return {"success": False, "message": "Could not create calendar event."}


def parse_datetime_window(
    *,
    date_str: str | None,
    start_time: str | None,
    duration_minutes: int = 60,
) -> tuple[datetime, datetime]:
    """Build UTC start/end from date and time strings."""
    now = datetime.now(timezone.utc)
    if date_str:
        try:
            base = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        except ValueError:
            base = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        base = now.replace(hour=0, minute=0, second=0, microsecond=0)

    hour, minute = 14, 0
    if start_time:
        parts = start_time.replace(".", ":").split(":")
        try:
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
        except ValueError:
            pass

    start = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    end = start + timedelta(minutes=duration_minutes)
    return start, end
