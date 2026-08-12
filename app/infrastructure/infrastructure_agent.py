"""Infrastructure action agent — print, conference booking, unsupported actions."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Literal, Optional

from app.chat.pending_infrastructure import get_pending
from app.config import get_settings
from app.infrastructure.conference_agent import handle_conference_query
from app.infrastructure.print import handle_print_document
from app.llm.client import cached_system, complete

logger = logging.getLogger(__name__)

SubIntent = Literal[
    "print_document",
    "book_conference_room",
    "unsupported_action",
]

ACTION_SYSTEM = """Classify office infrastructure ACTION requests (things to DO, not questions).

Return ONLY JSON:
{{
  "sub_intent": "print_document|book_conference_room|unsupported_action",
  "reason": "one sentence"
}}

print_document: user wants to print an uploaded document
book_conference_room: reserve/book a conference or meeting room
unsupported_action: parking, catering, or other actions not yet supported

Guesthouse booking is NOT this intent — only office conference/meeting rooms."""

PRINT_KEYWORDS = ("print this", "print it", "send to printer", "print the document", "print my")
CONFERENCE_KEYWORDS = (
    "conference room",
    "meeting room",
    "book a meeting",
    "book conference",
    "reserve a room for",
)
UNSUPPORTED_KEYWORDS = ("parking", "catering", "order food", "reserve parking")


def _keyword_sub_intent(query: str, *, has_document: bool) -> Dict[str, Any]:
    q = query.lower()
    if any(k in q for k in PRINT_KEYWORDS) or (has_document and "print" in q):
        return {"sub_intent": "print_document"}
    if any(k in q for k in CONFERENCE_KEYWORDS):
        return {"sub_intent": "book_conference_room"}
    if any(k in q for k in UNSUPPORTED_KEYWORDS):
        return {"sub_intent": "unsupported_action"}
    if "book" in q and ("room" in q or "meeting" in q):
        return {"sub_intent": "book_conference_room"}
    return {"sub_intent": "unsupported_action", "reason": "Could not classify action"}


def _classify_action(query: str, *, has_document: bool) -> Dict[str, Any]:
    try:
        ctx = "Document uploaded in session." if has_document else "No document uploaded."
        llm = complete(
            model=get_settings().classifier_model,
            system=cached_system(ACTION_SYSTEM),
            messages=[{"role": "user", "content": f"{ctx}\n\n{query}"}],
            max_tokens=150,
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
        logger.warning("Infrastructure action classify failed: %s", exc)
    return _keyword_sub_intent(query, has_document=has_document)


def handle_infrastructure_action(
    *,
    user_email: str,
    query: str,
    session_id: str | None = None,
    has_document: bool = False,
) -> Dict[str, Any]:
    pending = get_pending(session_id) if session_id else None
    if pending:
        sub: SubIntent = "book_conference_room"
    else:
        classified = _classify_action(query, has_document=has_document)
        sub = classified.get("sub_intent") or "unsupported_action"

    if sub == "print_document":
        if not has_document:
            return {
                "answer": (
                    "Please upload a PDF or TXT document in chat first, "
                    "then say 'print this'."
                ),
                "model_used": "infrastructure_action",
            }
        result = handle_print_document(user_email=user_email, session_id=session_id)
        return {
            "answer": result.get("answer") or "",
            "model_used": result.get("model_used") or "infrastructure_action",
            "department": "it",
        }

    if sub == "book_conference_room":
        result = handle_conference_query(
            user_email=user_email,
            query=query,
            session_id=session_id,
        )
        answer = (result.get("answer") or "").replace("**", "")
        return {
            "answer": answer,
            "model_used": result.get("model_used") or "infrastructure_action",
            "department": "it",
        }

    return {
        "answer": (
            "That office action isn't available yet. I can help you "
            "**print a document** (upload PDF first) or **book a conference room**. "
            "For parking or catering, contact facilities@ampcus.com."
        ).replace("**", ""),
        "model_used": "infrastructure_action",
        "department": "it",
    }
