"""Tests for inline pasted text detection and extraction."""

from __future__ import annotations

from app.documents.inline_text import (
    detect_inline_analysis,
    extract_inline_text,
    is_inline_text_analysis,
)

GAZA_EXHIBITION_BODY = (
    "The Saved Treasures of Gaza exhibition displayed 130 archaeological artefacts "
    "spanning 5,000 years of Gazan history at the Institut du monde arabe in Paris. "
    "Curated by Elodie Bouffard, the exhibition ran from April to December 2025, "
    "extended a month due to public interest, and featured items from Palestinian "
    "excavations and a private collection that could not be returned to Gaza due "
    "to the ongoing conflict."
)


def test_extract_inline_text_strips_summarize_command():
    query = f"{GAZA_EXHIBITION_BODY}\n\nSummarize this"
    body = extract_inline_text(query, "summarize")
    assert "Saved Treasures of Gaza" in body
    assert "summarize" not in body.lower()


def test_detect_inline_analysis_long_paste_with_command():
    query = f"{GAZA_EXHIBITION_BODY}\n\nSummarize this"
    assert detect_inline_analysis(query) == "summarize"
    assert is_inline_text_analysis(query) is True


def test_detect_inline_analysis_rejects_command_only():
    assert is_inline_text_analysis("Summarize this") is False
    assert detect_inline_analysis("Summarize this") is None


def test_detect_inline_analysis_key_takeaways():
    query = f"{GAZA_EXHIBITION_BODY}\n\nKey takeaways"
    assert detect_inline_analysis(query) == "takeaways"
