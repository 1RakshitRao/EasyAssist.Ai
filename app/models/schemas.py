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
    confirm_ticket: Optional[bool] = Field(
        default=None,
        description="True to create pending ticket; False to decline; omit for normal query",
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
    intent: Optional[str] = None
    intent_confidence: Optional[str] = None
    nlp_allowed: Optional[bool] = None
    block_kind: Optional[str] = None
    pending_ticket_confirmation: bool = False
    reservation_calendar: Optional[Dict[str, Any]] = None


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
    preview_kind: Optional[str] = None
    file_size_bytes: Optional[int] = None
    page_count: Optional[int] = None


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
    preview_kind: Optional[str] = None
    file_size_bytes: Optional[int] = None
    page_count: Optional[int] = None
    text: Optional[str] = None
    text_expired: bool = False


# --- Onboarding ---


class CreateEmployeeRequest(BaseModel):
    email: str = Field(..., min_length=3)
    full_name: str = Field(..., min_length=1)
    employee_id: Optional[str] = None
    department: str = Field(
        ...,
        description="engineering | data | hr | sales | compliance | legal",
    )
    role_title: str = Field(..., min_length=1)
    manager_email: Optional[str] = None
    office_location: Optional[str] = None
    joining_date: str = Field(..., description="ISO date YYYY-MM-DD")
    provision_login: bool = False


class EmployeeOut(BaseModel):
    email: str
    full_name: str
    employee_id: Optional[str] = None
    department: str
    role_title: str
    manager_email: Optional[str] = None
    office_location: Optional[str] = None
    joining_date: str
    onboarding_complete: bool = False
    onboarding_started_at: Optional[str] = None
    created_by: Optional[str] = None
    created_at: str
    active: bool = True


class CreateEmployeeResponse(BaseModel):
    employee: EmployeeOut
    tasks_generated: int
    temp_password: Optional[str] = None


class UpdateEmployeeRequest(BaseModel):
    full_name: Optional[str] = None
    employee_id: Optional[str] = None
    department: Optional[str] = None
    role_title: Optional[str] = None
    manager_email: Optional[str] = None
    office_location: Optional[str] = None
    joining_date: Optional[str] = None
    active: Optional[bool] = None
    onboarding_complete: Optional[bool] = None


class AdminTaskUpdate(BaseModel):
    task_title: Optional[str] = None
    task_description: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = Field(None, description="pending | completed | skipped")
    due_date: Optional[str] = None
    link_url: Optional[str] = None
    sort_order: Optional[int] = None


class AdminReminderUpdate(BaseModel):
    reminder_type: Optional[str] = None
    sent_at: Optional[str] = None
    delivery_status: Optional[str] = None
    channel: Optional[str] = None


class OnboardingTaskOut(BaseModel):
    id: str
    employee_email: str
    task_key: str
    task_title: str
    task_description: Optional[str] = None
    category: str
    status: str
    due_date: Optional[str] = None
    completed_at: Optional[str] = None
    reminder_count: int = 0
    last_reminded_at: Optional[str] = None
    link_url: Optional[str] = None
    department_specific: bool = False
    sort_order: int = 0


class EmployeeDetailResponse(BaseModel):
    employee: EmployeeOut
    tasks: List[OnboardingTaskOut] = Field(default_factory=list)
    tasks_generated: int = 0


class MyTasksResponse(BaseModel):
    email: str
    completed: int
    total: int
    percentage: float
    tasks_by_category: Dict[str, List[OnboardingTaskOut]] = Field(default_factory=dict)


class TaskStatusUpdate(BaseModel):
    status: str = Field(..., description="completed | skipped")


class OnboardingReminderOut(BaseModel):
    id: str
    employee_email: str
    task_id: Optional[str] = None
    reminder_type: str
    sent_at: str
    delivery_status: str = "sent"
    channel: str = "email"


class CompletionRateEntry(BaseModel):
    email: str
    name: str
    joining_date: str
    completed: int
    total: int
    percentage: float


class FollowupEntry(BaseModel):
    email: str
    name: str
    joining_date: str
    onboarding_day: int
    completed: int
    total: int
    percentage: float


class OnboardingOverviewResponse(BaseModel):
    new_hires_this_week: int
    completion_rates: List[CompletionRateEntry] = Field(default_factory=list)
    pending_by_category: Dict[str, int] = Field(default_factory=dict)
    employees_needing_followup: List[FollowupEntry] = Field(default_factory=list)


class OnboardingEmployeeDetailResponse(BaseModel):
    employee: EmployeeOut
    tasks: List[OnboardingTaskOut] = Field(default_factory=list)
    reminders: List[OnboardingReminderOut] = Field(default_factory=list)
    completed: int
    total: int
    percentage: float


# --- Guesthouse reservations ---


class GuesthouseOut(BaseModel):
    id: str
    name: str
    address: str
    city: str
    amenities: List[str] = Field(default_factory=list)
    room_count: int = 0


class RoomOut(BaseModel):
    id: str
    guesthouse_id: str
    room_number: str
    room_name: str
    capacity: int = 2
    amenities: List[str] = Field(default_factory=list)
    guesthouse_name: Optional[str] = None


class GuesthouseWithRoomsOut(GuesthouseOut):
    rooms: List[RoomOut] = Field(default_factory=list)


class ReservationOut(BaseModel):
    id: str
    confirmation_number: str
    employee_email: str
    room_id: str
    guesthouse_id: str
    checkin_date: str
    checkout_date: str
    purpose: str
    status: str
    guesthouse_name: Optional[str] = None
    guesthouse_address: Optional[str] = None
    room_number: Optional[str] = None
    room_name: Optional[str] = None
    created_at: Optional[str] = None
    approved_at: Optional[str] = None
    auto_approve_at: Optional[str] = None


class CreateReservationRequest(BaseModel):
    room_id: str
    checkin_date: str = Field(..., description="YYYY-MM-DD")
    checkout_date: str = Field(..., description="YYYY-MM-DD")
    purpose: str = Field(..., description="Business travel | Client meeting | Training | Team offsite | Other")


class ModifyReservationRequest(BaseModel):
    checkin_date: str
    checkout_date: str


class RejectReservationRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class OverrideReservationRequest(BaseModel):
    reason: str = Field(..., min_length=1)


class AdminCreateReservationRequest(BaseModel):
    employee_email: str = Field(..., min_length=3)
    room_id: str
    checkin_date: str = Field(..., description="YYYY-MM-DD")
    checkout_date: str = Field(..., description="YYYY-MM-DD")
    purpose: str = Field(default="Business travel")
    auto_confirm: bool = True


class AvailabilityConflictOut(BaseModel):
    room_id: Optional[str] = None
    guesthouse_name: Optional[str] = None
    room_number: Optional[str] = None
    date: Optional[str] = None
    proposed_status: Optional[str] = None
    employee_email: Optional[str] = None
    confirmation_number: Optional[str] = None
    reservation_id: Optional[str] = None
    reservation_status: Optional[str] = None
    reason: Optional[str] = None


class AvailabilityUploadResult(BaseModel):
    applied: int
    conflicts: List[AvailabilityConflictOut] = Field(default_factory=list)


class AvailabilityConflictResolve(BaseModel):
    room_id: str
    date: str
    proposed_status: str
    action: str = Field(..., description="skip | override")
    reservation_id: Optional[str] = None
    reason: Optional[str] = None


class OccupancyReportOut(BaseModel):
    from_date: str
    to_date: str
    total_room_days: int
    booked_days: int
    occupancy_pct: float
    total_reservations: int
