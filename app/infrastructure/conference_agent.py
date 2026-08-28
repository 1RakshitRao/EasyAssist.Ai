"""Conference room booking chat agent — Microsoft 365 / local cache."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from app.chat.pending_infrastructure import clear_pending, get_pending, save_pending
from app.config import get_settings
from app.infrastructure import graph_calendar, store
from app.llm.client import cached_system, complete, resolve_classifier_model

logger = logging.getLogger(__name__)

SubIntent = Literal[
    "check_availability",
    "book_room",
    "list_bookings",
    "cancel_booking",
    "unsupported_action",
]

SUB_INTENT_SYSTEM = """You classify conference room / meeting room chat messages.
Today is {today}.

Return ONLY JSON:
{{
  "sub_intent": "check_availability|book_room|list_bookings|cancel_booking|unsupported_action",
  "date": null or "YYYY-MM-DD",
  "start_time": null or "HH:MM" (24h),
  "duration_minutes": null or integer,
  "attendee_count": null or integer,
  "room_name": null or string,
  "title": null or string
}}

Use book_room when user wants to reserve a conference/meeting room.
Use check_availability for open rooms or what's available.
Guesthouse stays out of scope — only office conference/meeting rooms."""

KEYWORD_SUB: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("book_room", ("book a conference", "book a meeting", "reserve a room", "book conference", "book meeting")),
    ("check_availability", ("available room", "which rooms", "any rooms free", "room availability")),
    ("list_bookings", ("my bookings", "my meetings", "my reservations")),
    ("cancel_booking", ("cancel my meeting", "cancel booking", "cancel room")),
)


def _today() -> str:
    return date.today().isoformat()


def _is_confirm(text: str) -> bool:
    return bool(re.search(r"\b(yes|confirm|ok|okay|sure|go ahead|book it)\b", text.lower()))


def _is_cancel(text: str) -> bool:
    return bool(re.search(r"\b(no|cancel|never mind|stop)\b", text.lower()))


def _keyword_sub_intent(query: str) -> Dict[str, Any]:
    q = query.lower()
    for sub, kws in KEYWORD_SUB:
        if any(k in q for k in kws):
            return {"sub_intent": sub}
    if "conference" in q or "meeting room" in q:
        return {"sub_intent": "book_room"}
    return {"sub_intent": "check_availability"}


def _classify_sub_intent(query: str) -> Dict[str, Any]:
    try:
        llm = complete(
            model=resolve_classifier_model(),
            system=cached_system(SUB_INTENT_SYSTEM.format(today=_today())),
            messages=[{"role": "user", "content": query}],
            max_tokens=200,
        )
        text = (llm.text or "").strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", text, re.DOTALL)
            data = json.loads(m.group(0)) if m else {}
        if isinstance(data, dict) and data.get("sub_intent"):
            return data
    except Exception as exc:
        logger.warning("Conference sub-intent LLM failed: %s", exc)
    return _keyword_sub_intent(query)


def _format_room_list(rooms: List[Dict[str, Any]]) -> str:
    if not rooms:
        return "No conference rooms are available for that time."
    lines = ["Available rooms:"]
    for i, r in enumerate(rooms[:8], 1):
        cap = r.get("capacity") or "?"
        name = r.get("room_name") or r.get("name") or "Room"
        av = r.get("av_equipment_json") or r.get("av_equipment") or ""
        lines.append(f"{i}. {name} — capacity {cap}{(' · ' + str(av)) if av else ''}")
    lines.append("\nReply with the room number to book, or say 'cancel'.")
    return "\n".join(lines)


def _handle_book_room(
    *,
    user_email: str,
    query: str,
    session_id: str | None,
    slots: Dict[str, Any],
) -> Dict[str, Any]:
    pending = get_pending(session_id) if session_id else None
    if pending and pending.get("step") == "confirm":
        if _is_cancel(query):
            clear_pending(session_id or "")
            return {"answer": "Booking cancelled.", "model_used": "conference_agent"}
        if _is_confirm(query):
            room = pending.get("room") or {}
            start_s = pending.get("start")
            end_s = pending.get("end")
            if not room or not start_s or not end_s:
                clear_pending(session_id or "")
                return {"answer": "Booking session expired. Please start again.", "model_used": "conference_agent"}
            start = datetime.fromisoformat(start_s)
            end = datetime.fromisoformat(end_s)
            result = graph_calendar.create_booking(
                user_email=user_email,
                room_email=str(room.get("room_email") or ""),
                room_name=str(room.get("room_name") or "Conference Room"),
                start=start,
                end=end,
                title=str(pending.get("title") or "Meeting"),
            )
            clear_pending(session_id or "")
            if result.get("success"):
                msg = str(result.get("message") or "Room booked.")
                msg = msg.replace("**", "")
                return {"answer": msg, "model_used": "conference_agent"}
            return {
                "answer": result.get("message") or "Booking failed.",
                "model_used": "conference_agent",
            }

    if pending and pending.get("step") == "pick_room":
        rooms = pending.get("rooms") or []
        if _is_cancel(query):
            clear_pending(session_id or "")
            return {"answer": "Booking cancelled.", "model_used": "conference_agent"}
        pick = re.search(r"\b(\d+)\b", query)
        if pick:
            idx = int(pick.group(1)) - 1
            if 0 <= idx < len(rooms):
                room = rooms[idx]
                save_pending(
                    session_id or "",
                    {
                        "step": "confirm",
                        "room": room,
                        "start": pending.get("start"),
                        "end": pending.get("end"),
                        "title": pending.get("title") or "Meeting",
                    },
                )
                name = room.get("room_name") or "the room"
                return {
                    "answer": f"Confirm booking **{name}**? Reply yes to confirm or no to cancel.",
                    "model_used": "conference_agent",
                }
        return {
            "answer": "Please reply with the room number from the list, or say cancel.",
            "model_used": "conference_agent",
        }

    date_str = slots.get("date") or _today()
    if "tomorrow" in query.lower():
        date_str = (date.today() + timedelta(days=1)).isoformat()

    start_time = slots.get("start_time")
    if not start_time:
        m = re.search(r"(\d{1,2})\s*(?::(\d{2}))?\s*(am|pm)?", query.lower())
        if m:
            h = int(m.group(1))
            mn = int(m.group(2) or 0)
            ap = m.group(3)
            if ap == "pm" and h < 12:
                h += 12
            if ap == "am" and h == 12:
                h = 0
            start_time = f"{h:02d}:{mn:02d}"

    duration = int(slots.get("duration_minutes") or 60)
    attendees = int(slots.get("attendee_count") or 1)

    start, end = graph_calendar.parse_datetime_window(
        date_str=date_str,
        start_time=start_time,
        duration_minutes=duration,
    )

    rooms = graph_calendar.get_available_rooms(
        start=start,
        end=end,
        min_capacity=attendees,
    )
    if not rooms:
        return {
            "answer": (
                f"No conference rooms available on {date_str} "
                f"for {attendees}+ people. Try a different time."
            ),
            "model_used": "conference_agent",
        }

    if len(rooms) == 1:
        room = rooms[0]
        save_pending(
            session_id or "",
            {
                "step": "confirm",
                "room": room,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "title": slots.get("title") or "Meeting",
            },
        )
        name = room.get("room_name") or "Conference Room"
        return {
            "answer": (
                f"Only {name} is available {date_str} "
                f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}. "
                "Reply yes to book or no to cancel."
            ),
            "model_used": "conference_agent",
        }

    save_pending(
        session_id or "",
        {
            "step": "pick_room",
            "rooms": rooms,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "title": slots.get("title") or "Meeting",
        },
    )
    return {
        "answer": _format_room_list(rooms),
        "model_used": "conference_agent",
    }


def _handle_check_availability(
    *,
    user_email: str,
    query: str,
    slots: Dict[str, Any],
) -> Dict[str, Any]:
    date_str = slots.get("date") or _today()
    if "tomorrow" in query.lower():
        date_str = (date.today() + timedelta(days=1)).isoformat()
    start, end = graph_calendar.parse_datetime_window(
        date_str=date_str,
        start_time=slots.get("start_time"),
        duration_minutes=int(slots.get("duration_minutes") or 60),
    )
    rooms = graph_calendar.get_available_rooms(
        start=start,
        end=end,
        min_capacity=int(slots.get("attendee_count") or 1),
    )
    return {"answer": _format_room_list(rooms), "model_used": "conference_agent"}


def handle_conference_query(
    *,
    user_email: str,
    query: str,
    session_id: str | None = None,
) -> Dict[str, Any]:
    pending = get_pending(session_id) if session_id else None
    if pending:
        slots = {"sub_intent": "book_room"}
    else:
        slots = _classify_sub_intent(query)

    sub = str(slots.get("sub_intent") or "book_room")

    if sub == "book_room":
        return _handle_book_room(
            user_email=user_email,
            query=query,
            session_id=session_id,
            slots=slots,
        )
    if sub == "check_availability":
        return _handle_check_availability(
            user_email=user_email,
            query=query,
            slots=slots,
        )
    if sub == "list_bookings":
        return {
            "answer": "View your upcoming meetings in Outlook calendar.",
            "model_used": "conference_agent",
        }
    if sub == "cancel_booking":
        return {
            "answer": "Cancel meeting room bookings in Outlook — open the event and remove the room.",
            "model_used": "conference_agent",
        }
    return {
        "answer": "I can help book or check availability for conference rooms. What date and time?",
        "model_used": "conference_agent",
    }
