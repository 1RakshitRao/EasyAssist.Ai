"""Shared HelpdeskState — the contract between LangGraph nodes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class HelpdeskState(TypedDict, total=False):
    query: str
    normalized_query: str
    department_hint: Optional[str]
    department: str
    severity: str  # routine | high
    classify_reason: str
    chunks: List[Dict[str, Any]]
    sources: List[str]
    attempted_depts: List[str]
    retry_count: int
    escalated: bool
    escalation_reason: Optional[str]
    ticket_id: Optional[str]
    answer: str
    model_used: str
    token_usage: Dict[str, int]
    cached: bool
    context_used: bool
    node_timings: Dict[str, float]
    user_id: Optional[str]
    user_email: Optional[str]
