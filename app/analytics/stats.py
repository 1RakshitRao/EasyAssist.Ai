"""In-memory query analytics for the dashboard (resets on process restart)."""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.analytics.costing import estimate_query_costs

_lock = threading.Lock()

_stats: Dict[str, Any] = {
    "total_queries": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "unknown_tickets_created": 0,
    "escalated": 0,
    "by_department": defaultdict(int),
    "by_severity": defaultdict(int),
    "by_model_role": defaultdict(int),
    "latency_ms_sum": 0.0,
    "cost_actual_sum": 0.0,
    "cost_opus_sum": 0.0,
    "recent": [],
    "cost_series": [],  # chronological for charts (oldest → newest)
}

_RECENT_MAX = 40


def reset_stats() -> None:
    """Clear session analytics (dashboard starts empty until real queries)."""
    with _lock:
        _stats["total_queries"] = 0
        _stats["cache_hits"] = 0
        _stats["cache_misses"] = 0
        _stats["unknown_tickets_created"] = 0
        _stats["escalated"] = 0
        _stats["by_department"] = defaultdict(int)
        _stats["by_severity"] = defaultdict(int)
        _stats["by_model_role"] = defaultdict(int)
        _stats["latency_ms_sum"] = 0.0
        _stats["cost_actual_sum"] = 0.0
        _stats["cost_opus_sum"] = 0.0
        _stats["recent"] = []
        _stats["cost_series"] = []


def record_query(response: Dict[str, Any], *, cached: bool) -> None:
    with _lock:
        _stats["total_queries"] += 1
        if cached:
            _stats["cache_hits"] += 1
        else:
            _stats["cache_misses"] += 1

        dept = (response.get("department") or "unknown").lower()
        sev = (response.get("severity") or "routine").lower()
        _stats["by_department"][dept] += 1
        _stats["by_severity"][sev] += 1

        if response.get("ticket_id") and dept == "unknown" and not cached:
            _stats["unknown_tickets_created"] += 1
        if response.get("escalated"):
            _stats["escalated"] += 1

        timings = response.get("node_timings") or {}
        total_ms = float(sum(timings.values())) if timings else 0.0
        _stats["latency_ms_sum"] += total_ms

        costs = estimate_query_costs(
            model_used=response.get("model_used") or "",
            token_usage=response.get("token_usage") or {},
            cached=cached,
            severity=sev,
            escalated=bool(response.get("escalated")),
        )
        _stats["by_model_role"][costs["model_role"]] += 1
        _stats["cost_actual_sum"] += costs["cost_actual_usd"]
        _stats["cost_opus_sum"] += costs["cost_opus_always_usd"]

        entry = {
            "question": (response.get("_question") or "")[:120],
            "department": dept,
            "severity": sev,
            "classify_reason": (response.get("classify_reason") or "")[:160],
            "cached": cached,
            "cache_similarity": response.get("cache_similarity"),
            "escalated": bool(response.get("escalated")),
            "ticket_id": response.get("ticket_id"),
            "model_used": response.get("model_used") or "",
            "model_role": costs["model_role"],
            "latency_ms": round(total_ms, 1),
            "node_timings": dict(timings),
            "input_tokens": costs["input_tokens"],
            "output_tokens": costs["output_tokens"],
            "cost_actual_usd": costs["cost_actual_usd"],
            "cost_opus_always_usd": costs["cost_opus_always_usd"],
            "cost_savings_usd": costs["cost_savings_usd"],
            "at": datetime.now(timezone.utc).isoformat(),
        }
        _stats["recent"].insert(0, entry)
        _stats["recent"] = _stats["recent"][:_RECENT_MAX]
        _stats["cost_series"].append(
            {
                "n": _stats["total_queries"],
                "actual": costs["cost_actual_usd"],
                "opus": costs["cost_opus_always_usd"],
                "latency_ms": round(total_ms, 1),
                "department": dept,
                "model_role": costs["model_role"],
            }
        )
        _stats["cost_series"] = _stats["cost_series"][-_RECENT_MAX:]


def snapshot(
    open_tickets: int = 0,
    open_escalations: int = 0,
    kb_counts: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    with _lock:
        total = _stats["total_queries"]
        hits = _stats["cache_hits"]
        avg_latency = (_stats["latency_ms_sum"] / total) if total else 0.0
        actual = _stats["cost_actual_sum"]
        opus = _stats["cost_opus_sum"]
        return {
            "total_queries": total,
            "cache_hits": hits,
            "cache_misses": _stats["cache_misses"],
            "cache_hit_rate": round((hits / total) * 100, 1) if total else 0.0,
            "unknown_tickets_created": _stats["unknown_tickets_created"],
            "escalated": _stats["escalated"],
            "avg_latency_ms": round(avg_latency, 1),
            "by_department": dict(_stats["by_department"]),
            "by_severity": dict(_stats["by_severity"]),
            "by_model_role": dict(_stats["by_model_role"]),
            "recent": list(_stats["recent"]),
            "cost_series": list(_stats["cost_series"]),
            "cost_actual_sum_usd": round(actual, 6),
            "cost_opus_sum_usd": round(opus, 6),
            "cost_savings_sum_usd": round(max(opus - actual, 0.0), 6),
            "cost_savings_pct": round(((opus - actual) / opus) * 100, 1) if opus else 0.0,
            "avg_cost_actual_usd": round(actual / total, 6) if total else 0.0,
            "avg_cost_opus_usd": round(opus / total, 6) if total else 0.0,
            "open_tickets": open_tickets,
            "open_escalations": open_escalations,
            "kb_counts": kb_counts or {},
        }
