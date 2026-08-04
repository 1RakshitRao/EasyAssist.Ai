"""Pydantic request/response schemas for the REST API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1)
    department_hint: Optional[str] = None
    model_preference: Optional[str] = Field(
        default="auto",
        description="auto | routine | high | opus — answer-model tier override",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Chat session id; created automatically when omitted",
    )


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
    prompt_score: Optional[int] = None
    prompt_feedback: Optional[Dict[str, Any]] = None
    session_id: Optional[str] = None


class SessionCreateResponse(BaseModel):
    session_id: str


class SessionSummary(BaseModel):
    session_id: str
    title: str
    created_at: str
    last_message_at: str
    message_count: int


class SessionRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class SessionMessage(BaseModel):
    id: str
    role: str
    content: str
    created_at: str
    department: Optional[str] = None
    cost_usd: Optional[float] = None


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
    created_by_user_id: Optional[str] = None
    created_by_email: Optional[str] = None
    updated_by_user_id: Optional[str] = None
    updated_by_email: Optional[str] = None


class TicketResolveRequest(BaseModel):
    admin_notes: Optional[str] = None
    status: str = Field(default="resolved", description="resolved | assigned")


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=1)


class UserPublic(BaseModel):
    id: str
    email: str
    name: str = ""
    role: str
    active: bool = True
    access_restricted: bool = False
    created_at: str = ""


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPublic


class CreateUserRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=8)
    role: str = Field(..., description="employee | agent | admin")
    name: str = ""


class NlpQueryRequest(BaseModel):
    question: str = Field(..., min_length=1)
    session_id: Optional[str] = Field(
        default=None,
        description="Chat session id; created automatically when omitted",
    )


class NlpQueryResponse(BaseModel):
    answer: str
    allowed: bool
    blocked_reason: Optional[str] = None
    role: str
    block_kind: Optional[str] = None
    sql: Optional[str] = None  # formatted for display
    sql_raw: Optional[str] = None  # executed statement (admin)
    row_count: Optional[int] = None
    session_id: Optional[str] = None
    model_used: Optional[str] = None
    token_usage: Dict[str, int] = Field(default_factory=dict)
    cost_usd: Optional[float] = None


class CompanyFactCreate(BaseModel):
    category: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    detail_1: str = ""
    detail_2: str = ""
    active: bool = True


class CompanyFactOut(BaseModel):
    id: str
    category: str
    name: str
    description: Optional[str] = None
    detail_1: Optional[str] = None
    detail_2: Optional[str] = None
    active: int = 1
    created_at: str


class DocumentOption(BaseModel):
    id: str
    label: str
    description: str = ""
    needs_question: bool = False
    admin_only: bool = False


class DocumentUploadResponse(BaseModel):
    doc_id: str
    filename: str
    char_count: int
    session_id: str
    available_options: List[DocumentOption] = Field(default_factory=list)
    suggested_department: Optional[str] = None


class DocumentAnalyzeRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    operation: str = Field(..., min_length=1)
    question: Optional[str] = None


class DocumentAnalyzeResponse(BaseModel):
    operation: str
    result: str
    doc_id: str
    filename: str
    model_used: str = ""
    token_usage: Dict[str, int] = Field(default_factory=dict)
    cost_usd: float = 0.0
    session_id: Optional[str] = None


class DocumentPushRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    department: str = Field(..., description="hr | it | compliance | legal")
    title: Optional[str] = None


class DocumentPushResponse(BaseModel):
    chunks_created: int
    department: str
    doc_ids: List[str] = Field(default_factory=list)
    filename: str = ""


class DocumentActiveResponse(BaseModel):
    doc_id: str
    filename: str
    char_count: int
    created_at: str
    expires_at: str
    available_options: List[DocumentOption] = Field(default_factory=list)
    suggested_department: Optional[str] = None
