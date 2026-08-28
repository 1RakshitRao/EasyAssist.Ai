"""Cost helpers for audit attribution."""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.analytics.costing import cost_usd, estimate_query_costs, infer_role


def calculate_cost_usd(
    *,
    model_role: str,
    input_tokens: int,
    output_tokens: int,
    from_cache: bool,
) -> float:
    """Pure cost function — cache hits are free."""
    if from_cache:
        return 0.0
    return round(cost_usd(model_role, int(input_tokens or 0), int(output_tokens or 0)), 6)


def costs_for_query(
    *,
    model_used: str,
    token_usage: Optional[Dict[str, Any]],
    from_cache: bool,
    severity: str = "routine",
    escalated: bool = False,
) -> Dict[str, Any]:
    """Wrap existing estimator and normalize field names for audit rows."""
    est = estimate_query_costs(
        model_used=model_used,
        token_usage=token_usage,
        cached=from_cache,
        severity=severity,
        escalated=escalated,
    )
    role = est["model_role"] or infer_role(model_used)
    actual = calculate_cost_usd(
        model_role=role,
        input_tokens=est["input_tokens"],
        output_tokens=est["output_tokens"],
        from_cache=from_cache,
    )
    return {
        "model_role": role,
        "input_tokens": est["input_tokens"],
        "output_tokens": est["output_tokens"],
        "cost_usd": actual,
        "cost_opus_always_usd": est["cost_opus_always_usd"],
        "cost_savings_usd": round(max(est["cost_opus_always_usd"] - actual, 0.0), 6),
    }


