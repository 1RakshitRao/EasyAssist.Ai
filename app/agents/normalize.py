"""Query normalization — single source of truth for cache keys and retrieval."""

from __future__ import annotations

import re


_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")


def normalize_query(text: str) -> str:
    """Lowercase, strip, collapse whitespace, remove meaning-neutral punctuation."""
    if not text:
        return ""
    cleaned = text.strip().lower()
    cleaned = _PUNCT_RE.sub(" ", cleaned)
    cleaned = _SPACE_RE.sub(" ", cleaned).strip()
    return cleaned
