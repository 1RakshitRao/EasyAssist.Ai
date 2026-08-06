"""Onboarding REST API — HR admin + employee self-service."""

from __future__ import annotations

import secrets
import string
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.auth.deps import AdminUser, CurrentUser
from app.auth.users import create_user, get_user_by_email
from app.models.schemas import (
    AdminReminderUpdate,
    AdminTaskUpdate,
    CreateEmployeeRequest,
    CreateEmployeeResponse,
    EmployeeDetailResponse,
    EmployeeOut,
    MyTasksResponse,
    OnboardingEmployeeDetailResponse,
    OnboardingOverviewResponse,
    OnboardingTaskOut,
    TaskStatusUpdate,
    TicketResponse,
    UpdateEmployeeRequest,
)
from app.onboarding import store
from app.onboarding.task_generator import generate_tasks
from app.tickets.store import list_tickets_for_user

router = APIRouter(tags=["onboarding"])


def _employee_out(data: dict) -> EmployeeOut:
    return EmployeeOut(
        email=data["email"],
        full_name=data["full_name"],
        employee_id=data.get("employee_id"),
        department=data["department"],
        role_title=data["role_title"],
        manager_email=data.get("manager_email"),
        office_location=data.get("office_location"),
        joining_date=data["joining_date"],
        onboarding_complete=bool(data.get("onboarding_complete")),
        onboarding_started_at=data.get("onboarding_started_at"),
        created_by=data.get("created_by"),
        created_at=data["created_at"],
        active=bool(data.get("active", True)),
    )


def _task_out(data: dict) -> OnboardingTaskOut:
    return OnboardingTaskOut(
        id=data["id"],
        employee_email=data["employee_email"],
        task_key=data["task_key"],
        task_title=data["task_title"],
        task_description=data.get("task_description"),
        category=data["category"],
        status=data["status"],
        due_date=data.get("due_date"),
        completed_at=data.get("completed_at"),
        reminder_count=int(data.get("reminder_count") or 0),
        last_reminded_at=data.get("last_reminded_at"),
        link_url=data.get("link_url"),
        department_specific=bool(data.get("department_specific")),
        sort_order=int(data.get("sort_order") or 0),
    )


def _gen_temp_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$"
    return "".join(secrets.choice(alphabet) for _ in range(length))


@router.post("/admin/employees", response_model=CreateEmployeeResponse, status_code=201)
def create_employee_endpoint(req: CreateEmployeeRequest, admin: AdminUser):
    try:
        employee = store.create_employee(
            email=req.email,
            full_name=req.full_name,
            employee_id=req.employee_id,
            department=req.department,
            role_title=req.role_title,
            manager_email=req.manager_email,
            office_location=req.office_location,
            joining_date=req.joining_date,
            created_by=str(admin.get("email") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    tasks = generate_tasks(employee)
    temp_password: Optional[str] = None

    if req.provision_login:
        if not get_user_by_email(req.email):
            temp_password = _gen_temp_password()
            try:
                create_user(
                    email=req.email,
                    password=temp_password,
                    role="employee",
                    name=req.full_name,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    return CreateEmployeeResponse(
        employee=_employee_out(employee),
        tasks_generated=len(tasks),
        temp_password=temp_password,
    )


@router.get("/admin/employees", response_model=list[EmployeeOut])
def list_employees_endpoint(
    _admin: AdminUser,
    department: Optional[str] = Query(None),
    onboarding_complete: Optional[bool] = Query(None),
):
    rows = store.list_employees(
        department=department,
        onboarding_complete=onboarding_complete,
    )
    return [_employee_out(r) for r in rows]


@router.get("/admin/employees/{email}", response_model=EmployeeDetailResponse)
def get_employee_endpoint(email: str, _admin: AdminUser):
    detail = store.get_employee_detail(email)
    if not detail:
        raise HTTPException(status_code=404, detail="Employee not found")
    return EmployeeDetailResponse(
        employee=_employee_out(detail["employee"]),
        tasks=[_task_out(t) for t in detail["tasks"]],
        tasks_generated=len(detail["tasks"]),
    )


@router.put("/admin/employees/{email}", response_model=EmployeeOut)
def update_employee_endpoint(email: str, req: UpdateEmployeeRequest, _admin: AdminUser):
    try:
        updated = store.update_employee(
            email,
            **req.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Employee not found")
    return _employee_out(updated)


@router.delete("/admin/employees/{email}", status_code=204)
def delete_employee_endpoint(email: str, _admin: AdminUser):
    if not store.delete_employee(email):
        raise HTTPException(status_code=404, detail="Employee not found")


@router.patch("/admin/tasks/{task_id}", response_model=OnboardingTaskOut)
def admin_update_task_endpoint(task_id: str, req: AdminTaskUpdate, _admin: AdminUser):
    try:
        updated = store.admin_update_task(
            task_id,
            **req.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_out(updated)


@router.delete("/admin/tasks/{task_id}", status_code=204)
def delete_task_endpoint(task_id: str, _admin: AdminUser):
    if not store.delete_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found")


@router.delete("/admin/reminders/{reminder_id}", status_code=204)
def delete_reminder_endpoint(reminder_id: str, _admin: AdminUser):
    if not store.delete_reminder(reminder_id):
        raise HTTPException(status_code=404, detail="Reminder not found")


@router.patch("/admin/reminders/{reminder_id}")
def admin_update_reminder_endpoint(
    reminder_id: str, req: AdminReminderUpdate, _admin: AdminUser
):
    updated = store.admin_update_reminder(
        reminder_id,
        **req.model_dump(exclude_unset=True),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Reminder not found")
    return updated


@router.get("/me/tasks", response_model=MyTasksResponse)
def my_tasks(user: CurrentUser):
    email = str(user.get("email") or "")
    tasks = store.get_tasks(email)
    if not tasks and not store.get_employee(email):
        return MyTasksResponse(
            email=email,
            completed=0,
            total=0,
            percentage=0.0,
            tasks_by_category={},
        )
    completed = sum(1 for t in tasks if t.get("status") == "completed")
    total = len(tasks)
    grouped = store.tasks_grouped_by_category(tasks)
    return MyTasksResponse(
        email=email,
        completed=completed,
        total=total,
        percentage=round(100 * completed / total, 1) if total else 0.0,
        tasks_by_category={
            cat: [_task_out(t) for t in items] for cat, items in grouped.items()
        },
    )


@router.patch("/me/tasks/{task_id}", response_model=OnboardingTaskOut)
def update_my_task(task_id: str, req: TaskStatusUpdate, user: CurrentUser):
    email = str(user.get("email") or "")
    try:
        updated = store.update_task_status(task_id, email, req.status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_out(updated)


def _ticket_out(ticket: dict) -> TicketResponse:
    ticket = dict(ticket)
    ticket.setdefault("ticket_type", "unknown")
    ticket.setdefault("severity", "routine")
    ticket.setdefault("created_by_user_id", None)
    ticket.setdefault("created_by_email", None)
    ticket.setdefault("updated_by_user_id", None)
    ticket.setdefault("updated_by_email", None)
    return TicketResponse(**ticket)


@router.get("/me/tickets", response_model=List[TicketResponse])
def my_tickets(user: CurrentUser) -> List[TicketResponse]:
    """Open helpdesk tickets filed by the signed-in employee."""
    email = str(user.get("email") or "")
    return [_ticket_out(t) for t in list_tickets_for_user(email, open_only=True)]


@router.get("/admin/onboarding/overview", response_model=OnboardingOverviewResponse)
def onboarding_overview(_admin: AdminUser):
    data = store.get_onboarding_overview()
    return OnboardingOverviewResponse(**data)


@router.get(
    "/admin/onboarding/employee/{email}",
    response_model=OnboardingEmployeeDetailResponse,
)
def onboarding_employee_detail(email: str, _admin: AdminUser):
    detail = store.get_employee_detail(email)
    if not detail:
        raise HTTPException(status_code=404, detail="Employee not found")
    return OnboardingEmployeeDetailResponse(
        employee=_employee_out(detail["employee"]),
        tasks=[_task_out(t) for t in detail["tasks"]],
        reminders=[
            {
                "id": r["id"],
                "employee_email": r["employee_email"],
                "task_id": r.get("task_id"),
                "reminder_type": r["reminder_type"],
                "sent_at": r["sent_at"],
                "delivery_status": r.get("delivery_status") or "sent",
                "channel": r.get("channel") or "email",
            }
            for r in detail["reminders"]
        ],
        completed=detail["completed"],
        total=detail["total"],
        percentage=detail["percentage"],
    )
