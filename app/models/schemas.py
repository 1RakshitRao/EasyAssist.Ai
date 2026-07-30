"""Pydantic request/response schemas for the REST API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1)
    department_hint: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    department: str
    severity: str
    sources: List[str] = Field(default_factory=list)
    cached: bool = False
    cache_similarity: Optional[float] = None
    model_used: str = ""
    attempted_depts: List[str] = Field(default_factory=list)
    retry_count: int = 0
    escalated: bool = False
    escalation_reason: Optional[str] = None
    ticket_id: Optional[str] = None
    classify_reason: str = ""
    context_used: bool = False
    token_usage: Dict[str, int] = Field(default_factory=dict)
    node_timings: Dict[str, float] = Field(default_factory=dict)


class IngestRequest(BaseModel):
    department: str
    title: str
    content: str
    metadata: Optional[Dict[str, Any]] = None


class IngestResponse(BaseModel):
    status: str
    department: str
    doc_id: str
    duplicate_of: Optional[str] = None
    duplicate_title: Optional[str] = None
    duplicate_distance: Optional[float] = None


class HealthResponse(BaseModel):
    status: str
    cache_backend: str
    chroma_collections: Dict[str, int]
    models: Dict[str, str]
    open_tickets: int = 0


class TicketAssignRequest(BaseModel):
    department: str = Field(..., description="hr | it | compliance | legal")
    admin_notes: Optional[str] = None


class TicketPromoteRequest(BaseModel):
    department: Optional[str] = Field(
        None, description="Required if ticket not yet assigned"
    )
    title: Optional[str] = None
    content: Optional[str] = Field(
        None,
        description="KB body; defaults to admin answer text or the original question",
    )
    answer: Optional[str] = Field(
        None, description="Canonical answer to store in the KB with the question"
    )
    admin_notes: Optional[str] = None


class TicketResponse(BaseModel):
    id: str
    question: str
    normalized_query: str
    ticket_type: str = "unknown"
    department: str
    severity: str = "routine"
    status: str
    reason: str
    attempted_depts: List[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
    assigned_department: Optional[str] = None
    kb_doc_id: Optional[str] = None
    admin_notes: Optional[str] = None


class TicketResolveRequest(BaseModel):
    admin_notes: Optional[str] = None
    status: str = Field(default="resolved", description="resolved | assigned")
