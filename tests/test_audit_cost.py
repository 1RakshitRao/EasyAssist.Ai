"""Unit tests for audit cost calculator."""

from __future__ import annotations

from app.audit.cost import calculate_cost_usd


def test_cache_hit_is_free():
    assert calculate_cost_usd(model_role="haiku", input_tokens=1000, output_tokens=500, from_cache=True) == 0.0
    assert calculate_cost_usd(model_role="opus", input_tokens=10000, output_tokens=2000, from_cache=True) == 0.0


def test_haiku_known_example():
    # 1M input @ $1 + 1M output @ $5 → $6; scale to 1k/200
    cost = calculate_cost_usd(
        model_role="haiku",
        input_tokens=1000,
        output_tokens=200,
        from_cache=False,
    )
    assert cost == round((1000 / 1_000_000) * 1.0 + (200 / 1_000_000) * 5.0, 6)


def test_sonnet_known_example():
    cost = calculate_cost_usd(
        model_role="sonnet",
        input_tokens=2000,
        output_tokens=400,
        from_cache=False,
    )
    assert cost == round((2000 / 1_000_000) * 3.0 + (400 / 1_000_000) * 15.0, 6)
