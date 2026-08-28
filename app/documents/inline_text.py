"""Detect and extract inline pasted text for document analysis operations."""

from __future__ import annotations

import re
from typing import Optional

# Minimum body length after stripping analysis commands (chars).
MIN_INLINE_BODY_CHARS = 200

# Longest phrases first — matched case-insensitively for detection/stripping.
_COMMAND_TO_OP: tuple[tuple[str, str], ...] = (
    ("summarize this document", "summarize"),
    ("summarize this", "summarize"),
    ("key takeaways", "takeaways"),
    ("action items", "actions"),
    ("explain simply", "explain"),
    ("explain this", "explain"),
    ("find risks", "risks"),
    ("what are the risks", "risks"),
    ("summarize", "summarize"),
    ("takeaways", "takeaways"),
    ("takeaway", "takeaways"),
    ("tl;dr", "summarize"),
    ("tldr", "summarize"),
    ("overview", "summarize"),
    ("actions", "actions"),
    ("explain", "explain"),
    ("risks", "risks"),
)

_ASK_PATTERNS: tuple[str, ...] = (
    r"what does .+ mean",
    r"what is .+ in this",
    r"why did .+ happen",
    r"who is .+ in this",
    r"how does .+ work",
)


def _normalize(text: str) -> str:
    return (text or "").strip()


def _find_operation(lower: str) -> Optional[str]:
    for phrase, op in _COMMAND_TO_OP:
        if phrase in lower:
            return op
    for pattern in _ASK_PATTERNS:
        if re.search(pattern, lower):
            return "ask"
    return None


def detect_inline_analysis(query: str) -> Optional[str]:
    """
    Return document op id when query contains an analysis command and substantial
    inline body text. Returns None if command-only or body too short.
    """
    text = _normalize(query)
    if not text:
        return None

    lower = text.lower()
    op = _find_operation(lower)
    if not op:
        return None

    body = extract_inline_text(text, op)
    if len(body) < MIN_INLINE_BODY_CHARS:
        return None
    return op


def is_inline_text_analysis(query: str) -> bool:
    return detect_inline_analysis(query) is not None


def extract_inline_text(query: str, operation: str | None = None) -> str:
    """Strip analysis command phrases; return remaining pasted body."""
    text = _normalize(query)
    if not text:
        return ""

    lower = text.lower()
    op = operation or _find_operation(lower)
    phrases = [p for p, mapped in _COMMAND_TO_OP if not op or mapped == op]
    if op == "ask":
        for pattern in _ASK_PATTERNS:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)
            lower = text.lower()

    # Strip from start and end (commands often bookend pasted content).
    changed = True
    while changed:
        changed = False
        stripped = text.strip()
        lower_stripped = stripped.lower()
        for phrase in sorted(phrases, key=len, reverse=True):
            if lower_stripped.startswith(phrase):
                text = stripped[len(phrase) :].strip(" \t\n\r:,-.")
                changed = True
                break
            if lower_stripped.endswith(phrase):
                text = stripped[: -len(phrase)].strip(" \t\n\r:,-.")
                changed = True
                break
        if not changed:
            text = stripped

    return text.strip()


def extract_inline_question(query: str) -> Optional[str]:
    """For ask op: pull a trailing question sentence from the message."""
    text = _normalize(query)
    if not text:
        return None
    if "?" in text:
        parts = text.split("?")
        candidate = parts[0].strip() + "?"
        if len(candidate) >= 10:
            return candidate
    for pattern in _ASK_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(0).strip()
    return None
