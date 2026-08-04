"""Sentence-aware text chunking for KB ingestion."""

from __future__ import annotations

import re
from typing import List

# Approximate tokens as words; target ~500 tokens with ~50 overlap
_TARGET_WORDS = 500
_OVERLAP_WORDS = 50
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")


def chunk_text(text: str, *, source_name: str = "") -> List[str]:
    """Split clean text into overlapping chunks suitable for Chroma ingest."""
    body = (text or "").strip()
    if not body:
        return []

    sentences = _SENTENCE_SPLIT.split(body)
    sentences = [s.strip() for s in sentences if s and s.strip()]
    if not sentences:
        words = body.split()
        return _window_words(words)

    chunks: List[str] = []
    current: List[str] = []
    word_count = 0

    for sent in sentences:
        sw = len(sent.split())
        if current and word_count + sw > _TARGET_WORDS:
            chunks.append(" ".join(current).strip())
            # overlap: keep last ~50 words of current
            overlap = " ".join(current).split()[-_OVERLAP_WORDS:]
            current = [" ".join(overlap)] if overlap else []
            word_count = len(overlap)
        current.append(sent)
        word_count += sw

    if current:
        chunk = " ".join(current).strip()
        if chunk:
            chunks.append(chunk)

    # Prefix source name lightly for context in first chunk only is done at push time
    _ = source_name
    return chunks or [body]


def _window_words(words: List[str]) -> List[str]:
    if not words:
        return []
    out: List[str] = []
    i = 0
    step = max(_TARGET_WORDS - _OVERLAP_WORDS, 1)
    while i < len(words):
        piece = words[i : i + _TARGET_WORDS]
        if not piece:
            break
        out.append(" ".join(piece))
        if i + _TARGET_WORDS >= len(words):
            break
        i += step
    return out
