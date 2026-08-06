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
    model_preference: Optional[str]  # auto | routine | high | opus
    session_id: Optional[str]
    conversation_history: List[Dict[str, str]]  # prior turns for answer agent
    # Supervisor routing
    intent: str
    intent_confidence: str
    intent_reason: str
    document_operation: Optional[str]
    user_role: str
    joining_date: Optional[str]
    document_id: Optional[str]
    has_document: bool
    onboarding_active: bool
    has_prior: bool
    cache_similarity: Optional[float]
    nlp_allowed: Optional[bool]
    block_kind: Optional[str]
    include_welcome: bool
    pending_ticket_confirmation: bool
    pending_ticket_payload: Optional[Dict[str, Any]]
    kb_miss_query: Optional[str]
    reservation_calendar: Optional[Dict[str, Any]]
