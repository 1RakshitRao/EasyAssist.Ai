"""USD cost estimates mapped to Haiku / Sonnet / Opus roles (Anthropic-equivalent rates).

Local Ollama runs are free at the meter, but we price each call by *role* so the
dashboard can show blended cost vs an always-Opus counterfactual.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.config import get_settings

# Default Anthropic-style list prices (USD per million tokens)
_DEFAULT_RATES = {
    "haiku": {"input": 1.0, "output": 5.0},
    "sonnet": {"input": 3.0, "output": 15.0},
    "opus": {"input": 15.0, "output": 75.0},
}


def _rates() -> Dict[str, Dict[str, float]]:
    s = get_settings()
    return {
        "haiku": {
            "input": float(s.price_haiku_input_per_mtok),
            "output": float(s.price_haiku_output_per_mtok),
        },
        "sonnet": {
            "input": float(s.price_sonnet_input_per_mtok),
            "output": float(s.price_sonnet_output_per_mtok),
        },
        "opus": {
            "input": float(s.price_opus_input_per_mtok),
            "output": float(s.price_opus_output_per_mtok),
        },
    }


def infer_role(model_used: str) -> str:
    """Map model_used string to haiku|sonnet|opus role."""
    settings = get_settings()
    text = (model_used or "").lower()
    if not text or text in {"none", "heuristic", "unknown", "hitl_ticket", "offline_excerpt"}:
        return "haiku"
    if "opus" in text or settings.answer_model_opus.lower() in text:
        return "opus"
    if "sonnet" in text or "mistral" in text or settings.answer_model_high.lower() in text:
        return "sonnet"
    if "haiku" in text or settings.answer_model_routine.lower() in text:
        return "haiku"
    if settings.classifier_model.lower() in text:
        return "haiku"
    # llama3.2 / small → haiku; llama3.1:8b → opus in our defaults
    if "llama3.1" in text or "8b" in text:
        return "opus"
    if "llama3.2" in text or "phi" in text:
        return "haiku"
    return "haiku"


def cost_usd(role: str, input_tokens: int, output_tokens: int) -> float:
    rates = _rates().get(role) or _DEFAULT_RATES["haiku"]
    return (input_tokens / 1_000_000.0) * rates["input"] + (
        output_tokens / 1_000_000.0
    ) * rates["output"]


def estimate_query_costs(
    *,
    model_used: str,
    token_usage: Optional[Dict[str, Any]],
    cached: bool,
    severity: str = "routine",
    escalated: bool = False,
) -> Dict[str, Any]:
    usage = token_usage or {}
    inp = int(usage.get("input_tokens") or 0)
    out = int(usage.get("output_tokens") or 0)

    # Sensible defaults when tokens weren't returned (e.g. heuristic path)
    if not cached and inp == 0 and out == 0:
        inp, out = 800, 200

    role = infer_role(model_used)
    if cached:
        actual = 0.0
        # Counterfactual: would have paid for a full Opus answer
        opus = cost_usd("opus", max(inp, 800), max(out, 200))
    else:
        actual = cost_usd(role, inp, out)
        opus = cost_usd("opus", inp, out)

    return {
        "model_role": role,
        "input_tokens": inp,
        "output_tokens": out,
        "cost_actual_usd": round(actual, 6),
        "cost_opus_always_usd": round(opus, 6),
        "cost_savings_usd": round(max(opus - actual, 0.0), 6),
    }
