"""Unit tests for prompt scorer parse + heuristic."""

from __future__ import annotations

from app.agents.scorer import heuristic_score, parse_score_response


def test_parse_score_response_ok():
    raw = '{"score": 8, "issues": ["minor"], "improved_query": "How do I reset VPN?", "reason": "good"}'
    parsed = parse_score_response(raw)
    assert parsed is not None
    assert parsed["score"] == 8
    assert parsed["improved_query"].startswith("How do I")


def test_parse_score_clamps():
    parsed = parse_score_response('{"score": 99, "issues": [], "improved_query": "x", "reason": ""}')
    assert parsed["score"] == 10
    parsed2 = parse_score_response('{"score": 0, "issues": [], "improved_query": "x", "reason": ""}')
    assert parsed2["score"] == 1


def test_heuristic_vague_is_low():
    result = heuristic_score("help")
    assert 1 <= result["score"] <= 5
    assert result["issues"]


def test_heuristic_specific_is_higher():
    result = heuristic_score(
        "How do I reset my VPN password after the MFA error code 0x800 on Outlook?"
    )
    assert result["score"] >= 6
