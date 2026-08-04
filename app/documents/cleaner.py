"""Normalize extracted document text."""

from __future__ import annotations

import re


_PAGE_NUM_RE = re.compile(
    r"(?m)^\s*(?:page\s+\d+(?:\s+of\s+\d+)?|\d+\s*/\s*\d+|\-\s*\d+\s*\-)\s*$",
    re.IGNORECASE,
)
_MULTI_NL = re.compile(r"\n{3,}")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")


def clean_text(raw: str) -> str:
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")
    text = _PAGE_NUM_RE.sub("", text)
    # Soft-wrap join: lines ending mid-sentence often have trailing hyphen
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    lines = []
    for line in text.split("\n"):
        lines.append(_MULTI_SPACE.sub(" ", line).strip())
    text = "\n".join(lines)
    text = _MULTI_NL.sub("\n\n", text)
    return text.strip()
