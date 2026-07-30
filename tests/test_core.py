"""Unit tests — no Anthropic key required for core paths."""

from __future__ import annotations

import hashlib

import pytest

from app.agents.answer import NO_CONTEXT_ANSWER, generate_answer
from app.agents.classifier import _parse_classification, classify_question, heuristic_classify
from app.agents.escalate import should_escalate
from app.agents.graph import route_after_classify, route_after_retrieve
from app.agents.normalize import normalize_query
from app.cache.redis_cache import ResponseCache
from app.config import get_settings
from app.llm.client import resolve_answer_model
from app.tickets.store import create_ticket, get_ticket, update_ticket


def test_normalize_query_idempotent_variants():
    a = normalize_query("  PTO Policy? ")
    b = normalize_query("pto policy")
    c = normalize_query("PTO   policy!!!")
    assert a == b == c == "pto policy"


def test_cache_key_stable_across_normalization():
    n1 = normalize_query("How many days leave do I get?")
    n2 = normalize_query("how many days leave do i get  ")
    assert ResponseCache.make_key(n1) == ResponseCache.make_key(n2)
    assert ResponseCache.make_key(n1, "hr") != ResponseCache.make_key(n1, "it")


def test_memory_cache_roundtrip():
    cache = ResponseCache()
    assert cache.backend in ("memory", "redis")
    payload = {"answer": "20 days", "cached": False}
    key_q = normalize_query("How many PTO days?")
    cache.set(key_q, payload)
    got = cache.get(key_q)
    assert got is not None
    assert got["answer"] == "20 days"


def test_classifier_parse_valid_json():
    parsed = _parse_classification(
        '{"department":"it","severity":"routine","reason":"vpn question"}'
    )
    assert parsed == {
        "department": "it",
        "severity": "routine",
        "reason": "vpn question",
    }


def test_classifier_parse_maps_low_to_routine():
    parsed = _parse_classification(
        '{"department":"hr","severity":"low","reason":"pto"}'
    )
    assert parsed is not None
    assert parsed["severity"] == "routine"


def test_classifier_heuristic_without_api_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    get_settings.cache_clear()
    result = classify_question("How do I reset my password?")
    assert result["department"] == "it"
    assert result["severity"] == "routine"
    assert result["reason"] == "heuristic_keyword_classifier"
    assert result["model_used"] == "heuristic"

    legal = classify_question("We may have a customer data breach")
    assert legal["department"] == "legal"
    assert legal["severity"] == "high"
    get_settings.cache_clear()


def test_heuristic_unknown_when_no_keywords():
    result = heuristic_classify("What is the cafeteria sushi menu this Friday?")
    assert result["department"] == "unknown"
    assert result["reason"] == "heuristic_no_match"


def test_route_after_classify_always_retrieves():
    assert route_after_classify({"department": "unknown"}) == "retrieve"
    assert route_after_classify({"department": "it"}) == "retrieve"


def test_answer_no_context_refuses():
    result = generate_answer("secret policy?", chunks=[], severity="routine")
    assert result["answer"] == NO_CONTEXT_ANSWER
    assert result["context_used"] is False
    assert result["model_used"] == "none"


def test_should_escalate_high_legal_hr_only():
    assert should_escalate("legal", "high") is True
    assert should_escalate("hr", "high") is True
    assert should_escalate("it", "high") is False
    assert should_escalate("legal", "routine") is False


def test_route_after_retrieve_empty_retries():
    assert (
        route_after_retrieve(
            {"chunks": [], "retry_count": 0, "department": "it", "severity": "routine"}
        )
        == "classify"
    )
    assert (
        route_after_retrieve(
            {"chunks": [], "retry_count": 1, "department": "it", "severity": "routine"}
        )
        == "create_ticket"
    )


def test_route_after_retrieve_escalate_vs_answer():
    chunks = [{"content": "x", "title": "t"}]
    assert (
        route_after_retrieve(
            {
                "chunks": chunks,
                "retry_count": 0,
                "department": "legal",
                "severity": "high",
            }
        )
        == "escalate"
    )
    assert (
        route_after_retrieve(
            {
                "chunks": chunks,
                "retry_count": 0,
                "department": "it",
                "severity": "routine",
            }
        )
        == "answer"
    )


def test_hitl_ticket_assign_and_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    get_settings.cache_clear()
    ticket = create_ticket(
        question="Weird question?",
        normalized_query="weird question",
        reason="heuristic_no_match",
    )
    assert ticket["department"] == "unknown"
    assert ticket["ticket_type"] == "unknown"
    assert ticket["status"] == "open"
    updated = update_ticket(
        ticket["id"],
        assigned_department="it",
        department="it",
        status="assigned",
    )
    assert updated is not None
    assert get_ticket(ticket["id"])["status"] == "assigned"
    get_settings.cache_clear()


def test_escalation_ticket_type(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    get_settings.cache_clear()
    from app.tickets.store import TICKET_TYPE_ESCALATION, list_tickets

    ticket = create_ticket(
        question="Possible data breach",
        normalized_query="possible data breach",
        reason="High-severity LEGAL",
        ticket_type=TICKET_TYPE_ESCALATION,
        department="legal",
        severity="high",
    )
    assert ticket["ticket_type"] == "escalation"
    assert ticket["department"] == "legal"
    open_esc = list_tickets(status="open", ticket_type="escalation")
    assert any(t["id"] == ticket["id"] for t in open_esc)
    get_settings.cache_clear()


def test_sha256_helper_matches_expected():
    material = "pto policy"
    digest = hashlib.sha256(material.encode()).hexdigest()
    assert ResponseCache.make_key(material) == f"helpdesk:faq:{digest}"


def test_cost_estimate_savings():
    from app.analytics.costing import estimate_query_costs

    costs = estimate_query_costs(
        model_used="ollama:llama3.2:latest",
        token_usage={"input_tokens": 1000, "output_tokens": 200},
        cached=False,
    )
    assert costs["model_role"] == "haiku"
    assert costs["cost_actual_usd"] < costs["cost_opus_always_usd"]
    assert costs["cost_savings_usd"] > 0

    cached = estimate_query_costs(
        model_used="ollama:llama3.2:latest",
        token_usage={"input_tokens": 1000, "output_tokens": 200},
        cached=True,
    )
    assert cached["cost_actual_usd"] == 0.0
    assert cached["cost_opus_always_usd"] > 0


def test_resolve_answer_model_roles(monkeypatch):
    monkeypatch.setenv("ANSWER_MODEL_ROUTINE", "haiku-sim")
    monkeypatch.setenv("ANSWER_MODEL_HIGH", "sonnet-sim")
    monkeypatch.setenv("ANSWER_MODEL_OPUS", "opus-sim")
    get_settings.cache_clear()
    assert resolve_answer_model("routine", escalated=False) == "haiku-sim"
    assert resolve_answer_model("high", escalated=False) == "sonnet-sim"
    assert resolve_answer_model("high", escalated=True) == "opus-sim"
    get_settings.cache_clear()


def test_semantic_cache_paraphrase_hit(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("SEMANTIC_CACHE_THRESHOLD", "0.65")
    get_settings.cache_clear()
    import app.cache.semantic_cache as sc

    sc._semantic = None
    cache = sc.get_semantic_cache()
    payload = {
        "answer": "Request via IT Service Catalog.",
        "department": "it",
        "severity": "routine",
        "sources": ["Laptop Request"],
        "cached": False,
        "context_used": True,
    }
    cache.store("how do i request a new laptop", payload)
    hit, sim = cache.lookup("i want a new laptop what should i do")
    assert hit is not None
    assert sim >= 0.65
    assert hit["answer"] == payload["answer"]
    miss, sim2 = cache.lookup("my laptop will not turn on at all")
    assert miss is None
    assert sim2 < 0.65
    sc._semantic = None
    get_settings.cache_clear()


def test_ingest_dedup_rejects_exact_title_and_near_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    get_settings.cache_clear()
    import app.rag.chroma_store as cs

    cs._store = None
    store = cs.get_store()
    store.add_documents(
        "hr",
        [
            {
                "id": "hr-dedup-seed",
                "title": "PTO Accrual Policy",
                "content": "Full-time employees accrue 20 days of paid time off per year.",
            }
        ],
        check_duplicates=False,
    )

    # Exact title match even with different wording
    match = store.find_near_duplicate(
        "hr",
        "pto accrual policy",
        "Something completely different about vacation.",
    )
    assert match is not None
    assert match["reason"] == "exact_title"
    assert match["id"] == "hr-dedup-seed"

    # Near-identical body should trip embedding gate
    with pytest.raises(cs.NearDuplicateError) as exc:
        store.add_documents(
            "hr",
            [
                {
                    "title": "Paid Time Off Accrual",
                    "content": "Full-time employees accrue 20 days of paid time off per year.",
                }
            ],
        )
    assert exc.value.match["id"] == "hr-dedup-seed"

    # Unrelated doc should be allowed
    ids = store.add_documents(
        "hr",
        [
            {
                "title": "Desk Hoteling Pilot",
                "content": "Employees may reserve desks weekly through the facilities portal.",
            }
        ],
    )
    assert len(ids) == 1
    cs._store = None
    get_settings.cache_clear()
