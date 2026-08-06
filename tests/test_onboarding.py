"""Tests for onboarding module — store, generator, agent, reminders, API."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.audit.db import init_audit_db
from app.onboarding import store
from app.onboarding.onboarding_agent import (
    detect_sub_intent,
    extract_task_key,
    handle_onboarding_query,
    is_onboarding_context,
)
from app.onboarding.reminder_job import run_onboarding_reminders_once
from app.onboarding.reminder_templates import (
    build_daily_reminder_email,
    build_escalation_email,
    build_welcome_message,
)
from app.onboarding.task_generator import (
    DEPARTMENT_TASKS,
    UNIVERSAL_TASKS,
    expected_task_count,
    generate_tasks,
)


@pytest.fixture()
def onboarding_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    from app.config import get_settings

    get_settings.cache_clear()
    init_audit_db()
    yield tmp_path
    get_settings.cache_clear()


def _create_employee(
    email: str = "newhire@ampcus.com",
    department: str = "engineering",
    joining_date: str | None = None,
    **kwargs,
):
    if joining_date is None:
        joining_date = date.today().isoformat()
    return store.create_employee(
        email=email,
        full_name=kwargs.get("full_name", "Sarah Johnson"),
        employee_id=kwargs.get("employee_id"),
        department=department,
        role_title=kwargs.get("role_title", "Software Engineer"),
        manager_email=kwargs.get("manager_email", "manager@ampcus.com"),
        office_location=kwargs.get("office_location"),
        joining_date=joining_date,
        created_by=kwargs.get("created_by", "admin@ampcus.com"),
    )


# --- Store ---


def test_create_employee_and_duplicate(onboarding_db):
    emp = _create_employee()
    assert emp["email"] == "newhire@ampcus.com"
    assert emp["department"] == "engineering"
    with pytest.raises(ValueError, match="already exists"):
        _create_employee()


def test_unknown_department_rejected(onboarding_db):
    with pytest.raises(ValueError, match="department must be one of"):
        _create_employee(department="marketing")


def test_mark_onboarding_complete(onboarding_db):
    _create_employee()
    store.mark_onboarding_complete("newhire@ampcus.com")
    emp = store.get_employee("newhire@ampcus.com")
    assert emp["onboarding_complete"] is True


# --- Task generator ---


def test_engineering_gets_11_tasks(onboarding_db):
    emp = _create_employee(department="engineering")
    tasks = generate_tasks(emp)
    assert len(tasks) == 11
    assert expected_task_count("engineering") == 11


def test_hr_gets_9_tasks(onboarding_db):
    emp = _create_employee(email="hrhire@ampcus.com", department="hr")
    tasks = generate_tasks(emp)
    assert len(tasks) == 9


def test_data_gets_10_tasks(onboarding_db):
    emp = _create_employee(email="datahire@ampcus.com", department="data")
    tasks = generate_tasks(emp)
    assert len(tasks) == 10


def test_generate_tasks_idempotent(onboarding_db):
    emp = _create_employee()
    first = generate_tasks(emp)
    second = generate_tasks(emp)
    assert len(first) == len(second)
    assert store.count_tasks_for_employee(emp["email"]) == 11


def test_unique_task_keys_per_employee(onboarding_db):
    emp = _create_employee()
    tasks = generate_tasks(emp)
    keys = [t["task_key"] for t in tasks]
    assert len(keys) == len(set(keys))


# --- Agent ---


def test_detect_sub_intent_checklist(onboarding_db):
    assert detect_sub_intent("show my onboarding checklist") == "show_checklist"
    assert detect_sub_intent("what do I need to do today?") == "show_checklist"
    assert (
        detect_sub_intent("I am a new hire. what am i suppose to do on my first day ?")
        == "show_checklist"
    )


def test_detect_sub_intent_completion(onboarding_db):
    assert detect_sub_intent("I've completed my MFA setup") == "mark_complete"
    assert detect_sub_intent("mark payroll as done") == "mark_complete"


def test_extract_task_key_mfa(onboarding_db):
    emp = _create_employee()
    tasks = generate_tasks(emp)
    key = extract_task_key("I've set up MFA", tasks)
    assert key == "setup_mfa"


def test_handle_checklist_no_llm(onboarding_db):
    emp = _create_employee()
    generate_tasks(emp)
    result = handle_onboarding_query(
        user_email=emp["email"],
        query="show my tasks",
        normalized_query="show my tasks",
    )
    assert result["model_used"] == "onboarding_agent"
    assert "PENDING" in result["answer"] or "tasks complete" in result["answer"]


def test_mark_complete_updates_db(onboarding_db):
    emp = _create_employee()
    generate_tasks(emp)
    result = handle_onboarding_query(
        user_email=emp["email"],
        query="I've set up MFA",
        normalized_query="i've set up mfa",
    )
    assert "marked complete" in result["answer"].lower() or "complete" in result["answer"].lower()
    tasks = store.get_tasks(emp["email"])
    mfa = next(t for t in tasks if t["task_key"] == "setup_mfa")
    assert mfa["status"] == "completed"


def test_all_tasks_complete_marks_onboarding(onboarding_db):
    emp = _create_employee()
    tasks = generate_tasks(emp)
    for t in tasks:
        store.update_task_status(t["id"], emp["email"], "completed")
    emp_row = store.get_employee(emp["email"])
    assert emp_row["onboarding_complete"] is True


def test_is_onboarding_context_in_window(onboarding_db):
    emp = _create_employee(joining_date=date.today().isoformat())
    generate_tasks(emp)
    assert is_onboarding_context(emp["email"], "hello") is True


def test_is_onboarding_context_complete_employee(onboarding_db):
    emp = _create_employee()
    generate_tasks(emp)
    store.mark_onboarding_complete(emp["email"])
    assert is_onboarding_context(emp["email"], "show my tasks") is False


# --- Reminder templates ---


def test_daily_reminder_email_has_subject_and_body(onboarding_db):
    emp = _create_employee()
    tasks = generate_tasks(emp)
    pending = [t for t in tasks if t["status"] == "pending"]
    mail = build_daily_reminder_email(emp, pending[:3], onboarding_day=3)
    assert mail["subject"]
    assert "Day 3" in mail["body"]
    assert pending[0]["task_title"] in mail["body"]


def test_escalation_email(onboarding_db):
    emp = _create_employee()
    tasks = generate_tasks(emp)
    mail = build_escalation_email(emp, tasks[:2])
    assert "incomplete" in mail["subject"].lower() or "⚠" in mail["subject"]
    assert emp["email"] in mail["body"]


def test_welcome_message(onboarding_db):
    emp = _create_employee()
    tasks = generate_tasks(emp)
    msg = build_welcome_message(emp, tasks)
    assert "Welcome" in msg
    assert "Sarah" in msg


# --- Reminder job ---


def test_reminder_job_day3(onboarding_db, monkeypatch):
    joined = (date.today() - timedelta(days=2)).isoformat()
    emp = _create_employee(joining_date=joined)
    generate_tasks(emp)
    now = datetime.now(timezone.utc)

    with patch("app.onboarding.reminder_job.send_email", return_value=True) as mock_send:
        sent = run_onboarding_reminders_once(now=now)
    assert sent >= 1
    mock_send.assert_called()
    reminders = store.list_reminders(emp["email"])
    assert len(reminders) >= 1


def test_reminder_job_no_duplicate_same_day(onboarding_db, monkeypatch):
    joined = (date.today() - timedelta(days=2)).isoformat()
    emp = _create_employee(joining_date=joined)
    generate_tasks(emp)
    now = datetime.now(timezone.utc)

    with patch("app.onboarding.reminder_job.send_email", return_value=True):
        first = run_onboarding_reminders_once(now=now)
        second = run_onboarding_reminders_once(now=now)
    assert first >= 1
    assert second == 0


def test_reminder_job_day7_escalation(onboarding_db, monkeypatch):
    joined = (date.today() - timedelta(days=6)).isoformat()
    emp = _create_employee(joining_date=joined)
    generate_tasks(emp)
    now = datetime.now(timezone.utc)

    with patch("app.onboarding.reminder_job.send_email", return_value=True) as mock_send:
        sent = run_onboarding_reminders_once(now=now)
    assert sent >= 1
    types = {r["reminder_type"] for r in store.list_reminders(emp["email"])}
    assert "escalation" in types or "daily_urgent" in types
    assert mock_send.call_count >= 1


# --- API ---


def test_admin_create_employee(client, admin_headers):
    res = client.post(
        "/admin/employees",
        headers=admin_headers,
        json={
            "email": "onboard@ampcus.com",
            "full_name": "Onboard Test",
            "department": "engineering",
            "role_title": "Engineer",
            "joining_date": date.today().isoformat(),
        },
    )
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["tasks_generated"] == 11
    assert data["employee"]["email"] == "onboard@ampcus.com"


def test_admin_create_unknown_department(client, admin_headers):
    res = client.post(
        "/admin/employees",
        headers=admin_headers,
        json={
            "email": "bad@ampcus.com",
            "full_name": "Bad Dept",
            "department": "marketing",
            "role_title": "Role",
            "joining_date": date.today().isoformat(),
        },
    )
    assert res.status_code == 422


def test_employee_cannot_create_admin_endpoint(client, employee_headers):
    res = client.post(
        "/admin/employees",
        headers=employee_headers,
        json={
            "email": "x@ampcus.com",
            "full_name": "X",
            "department": "hr",
            "role_title": "R",
            "joining_date": date.today().isoformat(),
        },
    )
    assert res.status_code == 403


def test_me_tasks(client, admin_headers, employee_headers):
    create = client.post(
        "/admin/employees",
        headers=admin_headers,
        json={
            "email": "employee@ampcus.com",
            "full_name": "Employee User",
            "department": "hr",
            "role_title": "HR Associate",
            "joining_date": date.today().isoformat(),
        },
    )
    assert create.status_code == 201, create.text

    res = client.get("/me/tasks", headers=employee_headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total"] == 9
    assert data["completed"] == 0
    assert "payroll" in data["tasks_by_category"]


def test_patch_task_ownership(client, admin_headers, employee_headers):
    create = client.post(
        "/admin/employees",
        headers=admin_headers,
        json={
            "email": "employee@ampcus.com",
            "full_name": "Employee User",
            "department": "sales",
            "role_title": "AE",
            "joining_date": date.today().isoformat(),
        },
    )
    assert create.status_code == 201
    detail = client.get(
        "/admin/employees/employee@ampcus.com",
        headers=admin_headers,
    )
    task_id = detail.json()["tasks"][0]["id"]

    ok = client.patch(
        f"/me/tasks/{task_id}",
        headers=employee_headers,
        json={"status": "completed"},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "completed"


def test_onboarding_overview(client, admin_headers):
    client.post(
        "/admin/employees",
        headers=admin_headers,
        json={
            "email": "overview@ampcus.com",
            "full_name": "Overview Test",
            "department": "legal",
            "role_title": "Counsel",
            "joining_date": date.today().isoformat(),
        },
    )
    res = client.get("/admin/onboarding/overview", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["new_hires_this_week"] >= 1
    assert isinstance(data["completion_rates"], list)
    assert isinstance(data["pending_by_category"], dict)


def test_onboarding_query_checklist(client, admin_headers, employee_headers):
    client.post(
        "/admin/employees",
        headers=admin_headers,
        json={
            "email": "employee@ampcus.com",
            "full_name": "Employee User",
            "department": "engineering",
            "role_title": "Engineer",
            "joining_date": date.today().isoformat(),
        },
    )
    res = client.post(
        "/query",
        headers=employee_headers,
        json={"question": "show my onboarding checklist"},
    )
    assert res.status_code == 200, res.text
    answer = res.json()["answer"]
    assert "Welcome" in answer or "tasks" in answer.lower() or "PENDING" in answer


def test_department_task_counts():
    assert len(UNIVERSAL_TASKS) == 7
    assert len(DEPARTMENT_TASKS) == 6


def test_delete_employee_cascades(onboarding_db):
    emp = _create_employee(email="delete@ampcus.com")
    tasks = generate_tasks(emp)
    store.insert_reminder(employee_email=emp["email"], reminder_type="daily")
    assert store.delete_employee(emp["email"]) is True
    assert store.get_employee(emp["email"]) is None
    assert store.get_tasks(emp["email"]) == []
    assert store.list_reminders(emp["email"]) == []


def test_admin_update_task_status(onboarding_db):
    emp = _create_employee(email="taskadmin@ampcus.com")
    tasks = generate_tasks(emp)
    task_id = tasks[0]["id"]
    updated = store.admin_update_task(task_id, status="completed")
    assert updated["status"] == "completed"


def test_delete_task(onboarding_db):
    emp = _create_employee(email="taskdel@ampcus.com")
    tasks = generate_tasks(emp)
    task_id = tasks[0]["id"]
    assert store.delete_task(task_id) is True
    assert store.get_task_by_id(task_id) is None


def test_update_employee_onboarding_complete(onboarding_db):
    emp = _create_employee(email="complete@ampcus.com")
    updated = store.update_employee(emp["email"], onboarding_complete=True)
    assert updated["onboarding_complete"] is True


def test_admin_delete_employee_api(client, admin_headers):
    create = client.post(
        "/admin/employees",
        headers=admin_headers,
        json={
            "email": "todelete@ampcus.com",
            "full_name": "To Delete",
            "department": "hr",
            "role_title": "Temp",
            "joining_date": date.today().isoformat(),
        },
    )
    assert create.status_code == 201
    res = client.delete("/admin/employees/todelete@ampcus.com", headers=admin_headers)
    assert res.status_code == 204
    get = client.get("/admin/employees/todelete@ampcus.com", headers=admin_headers)
    assert get.status_code == 404


def test_me_tasks_empty_without_onboarding_profile(client, employee_headers):
    res = client.get("/me/tasks", headers=employee_headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total"] == 0
    assert data["tasks_by_category"] == {}


def test_me_tickets_returns_own_open_only(client, employee_headers):
    from app.tickets.store import create_ticket

    open_ticket = create_ticket(
        "How do I reset VPN?",
        "reset vpn",
        "no_kb_match",
        created_by_email="employee@ampcus.com",
    )
    resolved_ticket = create_ticket(
        "Old resolved question",
        "old",
        "no_kb_match",
        created_by_email="employee@ampcus.com",
    )
    from app.tickets.store import update_ticket

    update_ticket(resolved_ticket["id"], status="resolved")

    create_ticket(
        "Someone else's ticket",
        "other",
        "no_kb_match",
        created_by_email="other@ampcus.com",
    )

    res = client.get("/me/tickets", headers=employee_headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert len(data) == 1
    assert data[0]["question"] == "How do I reset VPN?"
    assert data[0]["created_by_email"] == "employee@ampcus.com"


def test_me_tickets_forbidden_for_unauthenticated(client):
    res = client.get("/me/tickets")
    assert res.status_code == 401
