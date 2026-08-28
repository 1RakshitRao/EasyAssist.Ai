"""Guesthouse reservation chat agent — sub-intent routing and handlers."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Literal, Optional

from app.chat.pending_reservation import clear_pending, get_pending, save_pending
from app.audit.query_trace import get_tracer
from app.config import get_settings
from app.llm.client import cached_system, complete, resolve_classifier_model
from app.reservations import store
from app.reservations.calendar import build_calendar_payload
from app.reservations.confirmation import (
    format_date,
    format_reservation_summary,
)

logger = logging.getLogger(__name__)

SubIntent = Literal[
    "check_availability",
    "create_reservation",
    "list_reservations",
    "cancel_reservation",
    "modify_reservation",
    "show_details",
]

SUB_INTENT_SYSTEM = """You classify guesthouse reservation chat messages.
Today is {today}.

Return ONLY JSON:
{{
  "sub_intent": "check_availability|create_reservation|list_reservations|cancel_reservation|modify_reservation|show_details",
  "guesthouse_name": null or string like "4656 Westfield Blvd",
  "room_number": null or string,
  "checkin_date": null or "YYYY-MM-DD",
  "checkout_date": null or "YYYY-MM-DD",
  "purpose": null or one of: Business travel, Client meeting, Training, Team offsite, Other,
  "confirmation_number": null or "GH-YYYY-NNNN"
}}

Use create_reservation when user wants to book. Use check_availability for open dates.
Use list_reservations for my bookings. cancel/modify need confirmation_number when possible.
Use show_details for guesthouse info and amenities."""

KEYWORD_SUB_INTENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cancel_reservation", ("cancel my", "cancel reservation", "cancel booking")),
    ("modify_reservation", ("change dates", "modify", "reschedule", "move my stay")),
    ("check_availability", ("available", "availability", "open dates", "any rooms")),
    ("create_reservation", ("book a", "book the", "reserve", "reservation for", "need a room")),
    ("list_reservations", ("my booking", "my reservation", "upcoming stay", "my stays")),
    ("show_details", ("guesthouse", "amenities", "where is", "address")),
)

CONFIRM_WORDS = ("yes", "confirm", "book it", "go ahead", "proceed", "that's correct")
CANCEL_WORDS = ("no", "cancel", "never mind", "stop", "abort")


def _parse_sub_intent_json(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    sub = str(data.get("sub_intent") or "").lower().strip()
    valid = {
        "check_availability",
        "create_reservation",
        "list_reservations",
        "cancel_reservation",
        "modify_reservation",
        "show_details",
    }
    if sub not in valid:
        return None
    return data


def _keyword_sub_intent(query: str) -> Dict[str, Any]:
    q = query.lower()
    for sub, keywords in KEYWORD_SUB_INTENTS:
        if any(kw in q for kw in keywords):
            return {"sub_intent": sub}
    return {"sub_intent": "show_details"}


def detect_sub_intent(query: str) -> Dict[str, Any]:
    today = date.today().isoformat()
    settings = get_settings()
    try:
        if not get_settings().anthropic_api_key:
            raise RuntimeError("no api key")
        result = complete(
            model=resolve_classifier_model(),
            system=cached_system(SUB_INTENT_SYSTEM.format(today=today)),
            messages=[{"role": "user", "content": query}],
            max_tokens=250,
        )
        parsed = _parse_sub_intent_json(result.text or "")
        if parsed:
            return parsed
    except Exception as exc:
        logger.debug("Reservation sub-intent LLM fallback: %s", exc)
    return _keyword_sub_intent(query)


def _is_confirm(query: str) -> bool:
    q = query.lower().strip()
    return any(q == w or q.startswith(w + " ") for w in CONFIRM_WORDS)


def _is_cancel(query: str) -> bool:
    q = query.lower().strip()
    return any(q == w or q.startswith(w + " ") for w in CANCEL_WORDS)


def _resolve_guesthouse(name: Optional[str]) -> Optional[dict]:
    if name:
        gh = store.get_guesthouse_by_name(name)
        if gh:
            return gh
    houses = store.get_all_guesthouses()
    return houses[0] if houses else None


def _resolve_room(guesthouse_id: str, room_number: Optional[str]) -> Optional[dict]:
    gh = store.get_guesthouse_with_rooms(guesthouse_id)
    if not gh or not gh.get("rooms"):
        return None
    if room_number:
        for r in gh["rooms"]:
            if str(r.get("room_number")) == str(room_number).strip():
                return r
    return gh["rooms"][0]


def _calendar_for_parsed(parsed: dict) -> Optional[dict]:
    gh = _resolve_guesthouse(parsed.get("guesthouse_name"))
    if not gh:
        return None
    checkin = parsed.get("checkin_date")
    checkout = parsed.get("checkout_date")
    if checkin:
        start = date.fromisoformat(checkin)
        end = date.fromisoformat(checkout) if checkout else start + timedelta(days=41)
        return build_calendar_payload(
            guesthouse_id=gh["id"],
            from_date=start.isoformat(),
            to_date=end.isoformat(),
        )
    return build_calendar_payload(guesthouse_id=gh["id"])


def _handle_check_availability(parsed: dict) -> tuple[str, Optional[dict]]:
    gh = _resolve_guesthouse(parsed.get("guesthouse_name"))
    if not gh:
        return "No guesthouses are configured yet. Please contact HR.", None
    tracer = get_tracer()
    display = store.guesthouse_display_name(gh["id"])
    if tracer:
        tracer.agent_tool_call(
            "RESERVATION",
            "check_availability",
            {
                "guesthouse": display,
                "checkin": parsed.get("checkin_date") or "any",
                "checkout": parsed.get("checkout_date") or "any",
            },
        )
    try:
        cal = _calendar_for_parsed(parsed)
    except ValueError:
        cal = None
    if cal:
        if tracer:
            tracer.agent_tool_result("RESERVATION", "check_availability", "available")
        return (
            f"Guesthouse availability at {display}.",
            cal,
        )
    if tracer:
        tracer.agent_tool_result("RESERVATION", "check_availability", "unavailable")
    return "Could not load availability calendar.", None


def _handle_show_details(parsed: dict) -> str:
    gh = _resolve_guesthouse(parsed.get("guesthouse_name"))
    if not gh:
        lines = ["Company guesthouses:", ""]
        for g in store.get_all_guesthouses():
            lines.append(f"• {g['name']} — {g.get('address', '')}, {g.get('city', '')}")
        return "\n".join(lines) if len(lines) > 2 else "No guesthouses configured."

    detail = store.get_guesthouse_with_rooms(gh["id"])
    if not detail:
        return "Guesthouse not found."
    import json as _json

    amenities = _json.loads(detail.get("amenities") or "[]")
    lines = [
        detail["name"],
        detail.get("address", ""),
        f"City: {detail.get('city', '')}",
        f"Amenities: {', '.join(amenities) if amenities else '—'}",
        "",
        "Rooms:",
    ]
    for r in detail.get("rooms", []):
        lines.append(f"  Room {r['room_number']} — {r['room_name']} (capacity {r.get('capacity', 2)})")
    return "\n".join(lines)


def _handle_list(user_email: str) -> str:
    upcoming = store.get_upcoming_reservations(user_email)
    if not upcoming:
        return "You have no upcoming guesthouse reservations."
    lines = ["Your upcoming reservations:", ""]
    for res in upcoming:
        lines.append(format_reservation_summary(res))
        lines.append("")
    return "\n".join(lines).strip()


def _handle_cancel(user_email: str, parsed: dict) -> str:
    conf = (parsed.get("confirmation_number") or "").strip().upper()
    target = None
    if conf:
        target = store.get_reservation_by_confirmation(conf)
        if target and _email(target) != _email(user_email):
            return "That confirmation number belongs to another employee."
    else:
        upcoming = store.get_upcoming_reservations(user_email)
        if len(upcoming) == 1:
            target = upcoming[0]
        elif len(upcoming) > 1:
            return "You have multiple bookings. Please provide your confirmation number (GH-YYYY-NNNN)."

    if not target:
        return "I could not find a reservation to cancel. Share your confirmation number or book via chat."

    ok, msg = store.can_modify(target)
    if not ok:
        return msg
    try:
        cancelled = store.cancel_reservation(target["id"], user_email)
        from app.reservations.notifications import fire_cancel_notification

        fire_cancel_notification(cancelled)
        return f"Cancelled {cancelled.get('confirmation_number')}."
    except ValueError as exc:
        return str(exc)


def _handle_modify(user_email: str, parsed: dict, query: str) -> str:
    conf = (parsed.get("confirmation_number") or "").strip().upper()
    new_in = parsed.get("checkin_date")
    new_out = parsed.get("checkout_date")

    target = None
    if conf:
        target = store.get_reservation_by_confirmation(conf)
    else:
        upcoming = [r for r in store.get_upcoming_reservations(user_email) if r["status"] == store.STATUS_CONFIRMED]
        if len(upcoming) == 1:
            target = upcoming[0]

    if not target:
        return "Share your confirmation number and new check-in/check-out dates to modify a stay."
    if not new_in or not new_out:
        return (
            f"To modify {target.get('confirmation_number')}, tell me the new check-in and check-out dates "
            "(YYYY-MM-DD)."
        )
    try:
        updated = store.modify_reservation(target["id"], user_email, new_in, new_out)
        from app.reservations.notifications import fire_create_notifications

        fire_create_notifications(updated)
        return (
            f"Modification submitted for {updated.get('confirmation_number')}. "
            f"New dates: {format_date(new_in)} – {format_date(new_out)}. "
            "HR will re-approve the updated stay."
        )
    except ValueError as exc:
        return str(exc)


def _email(res: dict) -> str:
    return (res.get("employee_email") or "").strip().lower()


def _handle_create_flow(
    user_email: str,
    session_id: Optional[str],
    query: str,
    parsed: dict,
) -> str:
    pending = get_pending(session_id) if session_id else None

    if pending and _is_cancel(query):
        clear_pending(session_id)
        return "Booking cancelled. Let me know if you'd like to start over."

    if pending and pending.get("step") == "confirm" and _is_confirm(query):
        try:
            res = store.create_reservation(
                user_email,
                pending["room_id"],
                pending["checkin"],
                pending["checkout"],
                pending.get("purpose") or "Business travel",
            )
            clear_pending(session_id)
            from app.reservations.notifications import fire_create_notifications

            fire_create_notifications(res)
            conf = res.get("confirmation_number") or ""
            if tracer := get_tracer():
                tracer.agent_tool_result(
                    "RESERVATION",
                    "create_reservation",
                    f"submitted confirmation={conf}",
                )
            return (
                f"Reservation submitted!\n\n{format_reservation_summary(res)}\n\n"
                "HR will confirm shortly. You'll receive an email when approved."
            )
        except ValueError as exc:
            clear_pending(session_id)
            return str(exc)

    if pending and pending.get("step") == "purpose":
        purpose = query.strip()
        if purpose not in store.VISIT_PURPOSES:
            return f"Please choose a purpose: {', '.join(store.VISIT_PURPOSES)}"
        pending["purpose"] = purpose
        pending["step"] = "confirm"
        save_pending(session_id, pending)
        gh = store.get_room(pending["room_id"])
        return (
            f"Please confirm your booking:\n\n"
            f"{gh.get('guesthouse_name') if gh else 'Guesthouse'} — Room {gh.get('room_number') if gh else '?'}\n"
            f"{format_date(pending['checkin'])} – {format_date(pending['checkout'])}\n"
            f"Purpose: {purpose}\n\n"
            "Reply **yes** to submit or **no** to cancel."
        )

    checkin = parsed.get("checkin_date")
    checkout = parsed.get("checkout_date")
    gh = _resolve_guesthouse(parsed.get("guesthouse_name"))
    if not gh:
        return "Which guesthouse? We have 4656 Westfield Blvd and 4050 Westfield Blvd in Bloomington."

    room = _resolve_room(gh["id"], parsed.get("room_number"))
    if not room:
        return "I couldn't find that room. Try Room 1 or Room 2."

    if not checkin or not checkout:
        if pending and pending.get("step") == "dates":
            # try to parse from query
            dates = re.findall(r"\d{4}-\d{2}-\d{2}", query)
            if len(dates) >= 2:
                checkin, checkout = dates[0], dates[1]
        if not checkin or not checkout:
            save_pending(
                session_id,
                {
                    "step": "dates",
                    "guesthouse_id": gh["id"],
                    "room_id": room["id"],
                },
            )
            return (
                f"Booking {gh['name']} — Room {room['room_number']}.\n"
                "What are your check-in and check-out dates? (YYYY-MM-DD)"
            )

    avail = store.get_availability(checkin, checkout, gh["id"])
    room_avail = next((r for r in avail if r["room_id"] == room["id"]), None)
    display = store.guesthouse_display_name(gh["id"])
    tracer = get_tracer()
    if tracer:
        tracer.agent_tool_call(
            "RESERVATION",
            "check_availability",
            {
                "guesthouse": display,
                "room": room["room_number"],
                "checkin": checkin,
                "checkout": checkout,
            },
        )
    if not room_avail or not room_avail["available"]:
        if tracer:
            tracer.agent_tool_result("RESERVATION", "check_availability", "unavailable")
        return (
            f"Room {room['room_number']} is not available {format_date(checkin)} – "
            f"{format_date(checkout)}. Try different dates or another room."
        )
    if tracer:
        tracer.agent_tool_result("RESERVATION", "check_availability", "available")

    if not parsed.get("purpose") and not (pending and pending.get("purpose")):
        save_pending(
            session_id,
            {
                "step": "purpose",
                "guesthouse_id": gh["id"],
                "room_id": room["id"],
                "checkin": checkin,
                "checkout": checkout,
            },
        )
        return f"Dates look good. What is the purpose of your visit?\n\n{', '.join(store.VISIT_PURPOSES)}"

    purpose = parsed.get("purpose") or "Business travel"
    save_pending(
        session_id,
        {
            "step": "confirm",
            "guesthouse_id": gh["id"],
            "room_id": room["id"],
            "checkin": checkin,
            "checkout": checkout,
            "purpose": purpose,
        },
    )
    return (
        f"Please confirm your booking:\n\n"
        f"{gh['name']} — Room {room['room_number']}\n"
        f"{format_date(checkin)} – {format_date(checkout)}\n"
        f"Purpose: {purpose}\n\n"
        "Reply **yes** to submit or **no** to cancel."
    )


def handle_reservation_query(
    *,
    user_email: str,
    query: str,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Main entry from reservation graph node."""
    pending = get_pending(session_id) if session_id else None
    if pending and pending.get("step") in ("dates", "purpose", "confirm"):
        parsed = {"sub_intent": "create_reservation"}
    else:
        parsed = detect_sub_intent(query)

    sub = parsed.get("sub_intent") or "show_details"
    calendar_payload: Optional[dict] = None
    if tracer := get_tracer():
        tracer.agent_step("RESERVATION", f"Sub-intent: {sub}")

    if sub == "check_availability":
        answer, calendar_payload = _handle_check_availability(parsed)
    elif sub == "create_reservation":
        cal = _calendar_for_parsed(parsed)
        if cal and not (pending and pending.get("step") == "confirm" and _is_confirm(query)):
            answer = f"Guesthouse booking at {cal.get('display_name') or cal['guesthouse_name']}."
            calendar_payload = cal
        else:
            answer = _handle_create_flow(user_email, session_id, query, parsed)
    elif sub == "list_reservations":
        answer = _handle_list(user_email)
    elif sub == "cancel_reservation":
        answer = _handle_cancel(user_email, parsed)
    elif sub == "modify_reservation":
        answer = _handle_modify(user_email, parsed, query)
    else:
        answer = _handle_show_details(parsed)

    return {
        "answer": answer,
        "department": "hr",
        "severity": "routine",
        "sources": [],
        "model_used": "reservation_agent",
        "context_used": False,
        "token_usage": {},
        "reservation_calendar": calendar_payload,
    }
