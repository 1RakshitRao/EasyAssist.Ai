"""SQLite store for onboarding employees, tasks, and reminders."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.audit.db import connect, init_audit_db

logger = logging.getLogger(__name__)
_lock = threading.Lock()

VALID_DEPARTMENTS = frozenset(
    {"engineering", "data", "hr", "sales", "compliance", "legal"}
)
VALID_TASK_STATUSES = frozenset({"pending", "completed", "skipped"})
VALID_TASK_CATEGORIES = frozenset(
    {"identity", "payroll", "benefits", "documents", "apps"}
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _email(value: str | None) -> str:
    return (value or "").strip().lower()


def _row_to_dict(row) -> Dict[str, Any]:
    if row is None:
        return {}
    return dict(row)


def _employee_from_row(row) -> Dict[str, Any]:
    d = _row_to_dict(row)
    if d:
        d["onboarding_complete"] = bool(d.get("onboarding_complete"))
        d["active"] = bool(d.get("active"))
    return d


def _task_from_row(row) -> Dict[str, Any]:
    d = _row_to_dict(row)
    if d:
        d["department_specific"] = bool(d.get("department_specific"))
    return d


def create_employee(
    *,
    email: str,
    full_name: str,
    employee_id: str | None,
    department: str,
    role_title: str,
    manager_email: str | None = None,
    office_location: str | None = None,
    joining_date: str,
    created_by: str | None = None,
) -> Dict[str, Any]:
    init_audit_db()
    email_key = _email(email)
    dept = (department or "").strip().lower()
    if dept not in VALID_DEPARTMENTS:
        raise ValueError(
            f"department must be one of: {', '.join(sorted(VALID_DEPARTMENTS))}"
        )
    if not email_key or "@" not in email_key:
        raise ValueError("Valid email is required")
    now = _now()
    with _lock:
        with connect() as conn:
            existing = conn.execute(
                "SELECT email FROM employees WHERE email = ?", (email_key,)
            ).fetchone()
            if existing:
                raise ValueError("Employee already exists")
            if employee_id:
                dup = conn.execute(
                    "SELECT email FROM employees WHERE employee_id = ?",
                    (employee_id.strip(),),
                ).fetchone()
                if dup:
                    raise ValueError("employee_id already in use")
            conn.execute(
                """
                INSERT INTO employees (
                    email, full_name, employee_id, department, role_title,
                    manager_email, office_location, joining_date,
                    onboarding_complete, onboarding_started_at,
                    created_by, created_at, active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, ?, 1)
                """,
                (
                    email_key,
                    full_name.strip(),
                    (employee_id or "").strip() or None,
                    dept,
                    role_title.strip(),
                    _email(manager_email) or None,
                    (office_location or "").strip() or None,
                    joining_date.strip(),
                    _email(created_by) or None,
                    now,
                ),
            )
            conn.commit()
    logger.info("Created employee email=%s dept=%s", email_key, dept)
    return get_employee(email_key) or {}


def get_employee(email: str) -> Optional[Dict[str, Any]]:
    init_audit_db()
    email_key = _email(email)
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM employees WHERE email = ?", (email_key,)
        ).fetchone()
    return _employee_from_row(row) if row else None


def list_employees(
    *,
    department: str | None = None,
    onboarding_complete: bool | None = None,
) -> List[Dict[str, Any]]:
    init_audit_db()
    clauses: List[str] = []
    params: List[Any] = []
    if department:
        clauses.append("department = ?")
        params.append(department.strip().lower())
    if onboarding_complete is not None:
        clauses.append("onboarding_complete = ?")
        params.append(1 if onboarding_complete else 0)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM employees {where} ORDER BY joining_date DESC, email"
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_employee_from_row(r) for r in rows]


def update_employee(email: str, **fields: Any) -> Optional[Dict[str, Any]]:
    init_audit_db()
    email_key = _email(email)
    allowed = {
        "full_name",
        "employee_id",
        "department",
        "role_title",
        "manager_email",
        "office_location",
        "joining_date",
        "active",
        "onboarding_complete",
    }
    updates: Dict[str, Any] = {}
    for key, val in fields.items():
        if key not in allowed or val is None:
            continue
        if key == "department":
            dept = str(val).strip().lower()
            if dept not in VALID_DEPARTMENTS:
                raise ValueError(
                    f"department must be one of: {', '.join(sorted(VALID_DEPARTMENTS))}"
                )
            updates[key] = dept
        elif key in ("manager_email",):
            updates[key] = _email(str(val)) or None
        elif key == "active":
            updates[key] = 1 if val else 0
        elif key == "onboarding_complete":
            updates[key] = 1 if val else 0
        else:
            updates[key] = str(val).strip() if isinstance(val, str) else val
    if not updates:
        return get_employee(email_key)
    sets = ", ".join(f"{k} = ?" for k in updates)
    params = list(updates.values()) + [email_key]
    with _lock:
        with connect() as conn:
            cur = conn.execute(
                f"UPDATE employees SET {sets} WHERE email = ?", params
            )
            conn.commit()
            if cur.rowcount == 0:
                return None
    return get_employee(email_key)


def delete_employee(email: str) -> bool:
    init_audit_db()
    email_key = _email(email)
    with _lock:
        with connect() as conn:
            row = conn.execute(
                "SELECT email FROM employees WHERE email = ?", (email_key,)
            ).fetchone()
            if not row:
                return False
            conn.execute(
                "DELETE FROM onboarding_reminders WHERE employee_email = ?",
                (email_key,),
            )
            conn.execute(
                "DELETE FROM onboarding_tasks WHERE employee_email = ?",
                (email_key,),
            )
            conn.execute("DELETE FROM employees WHERE email = ?", (email_key,))
            conn.commit()
    logger.info("Deleted employee email=%s", email_key)
    return True


def mark_onboarding_complete(email: str) -> None:
    init_audit_db()
    email_key = _email(email)
    now = _now()
    with _lock:
        with connect() as conn:
            conn.execute(
                """
                UPDATE employees
                SET onboarding_complete = 1
                WHERE email = ?
                """,
                (email_key,),
            )
            conn.commit()


def set_onboarding_started_at(email: str) -> None:
    init_audit_db()
    email_key = _email(email)
    now = _now()
    with _lock:
        with connect() as conn:
            conn.execute(
                """
                UPDATE employees
                SET onboarding_started_at = ?
                WHERE email = ? AND onboarding_started_at IS NULL
                """,
                (now, email_key),
            )
            conn.commit()


def count_tasks_for_employee(email: str) -> int:
    init_audit_db()
    email_key = _email(email)
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM onboarding_tasks WHERE employee_email = ?",
            (email_key,),
        ).fetchone()
    return int(row["c"]) if row else 0


def insert_tasks(tasks: List[Dict[str, Any]]) -> int:
    init_audit_db()
    if not tasks:
        return 0
    with _lock:
        with connect() as conn:
            for t in tasks:
                conn.execute(
                    """
                    INSERT INTO onboarding_tasks (
                        id, employee_email, task_key, task_title, task_description,
                        category, status, due_date, completed_at, reminder_count,
                        last_reminded_at, link_url, department_specific, sort_order
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, NULL, ?, ?, ?)
                    """,
                    (
                        t["id"],
                        _email(t["employee_email"]),
                        t["task_key"],
                        t["task_title"],
                        t.get("task_description"),
                        t["category"],
                        t.get("status", "pending"),
                        t.get("due_date"),
                        t.get("link_url"),
                        1 if t.get("department_specific") else 0,
                        int(t.get("sort_order") or 0),
                    ),
                )
            conn.commit()
    return len(tasks)


def get_tasks(email: str) -> List[Dict[str, Any]]:
    init_audit_db()
    email_key = _email(email)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM onboarding_tasks
            WHERE employee_email = ?
            ORDER BY sort_order ASC, task_title ASC
            """,
            (email_key,),
        ).fetchall()
    return [_task_from_row(r) for r in rows]


def get_task_by_id(task_id: str) -> Optional[Dict[str, Any]]:
    init_audit_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM onboarding_tasks WHERE id = ?", (task_id,)
        ).fetchone()
    return _task_from_row(row) if row else None


def update_task_status(
    task_id: str,
    employee_email: str,
    status: str,
) -> Optional[Dict[str, Any]]:
    init_audit_db()
    status_key = (status or "").strip().lower()
    if status_key not in VALID_TASK_STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(VALID_TASK_STATUSES))}")
    email_key = _email(employee_email)
    now = _now()
    completed_at = now if status_key == "completed" else None
    with _lock:
        with connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM onboarding_tasks
                WHERE id = ? AND employee_email = ?
                """,
                (task_id, email_key),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                """
                UPDATE onboarding_tasks
                SET status = ?, completed_at = ?
                WHERE id = ? AND employee_email = ?
                """,
                (status_key, completed_at, task_id, email_key),
            )
            conn.commit()
    task = get_task_by_id(task_id)
    if task and status_key == "completed":
        pending = count_pending_tasks(email_key)
        if pending == 0:
            mark_onboarding_complete(email_key)
    return task


def admin_update_task(task_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    init_audit_db()
    allowed = {
        "task_title",
        "task_description",
        "category",
        "status",
        "due_date",
        "link_url",
        "sort_order",
    }
    updates: Dict[str, Any] = {}
    for key, val in fields.items():
        if key not in allowed or val is None:
            continue
        if key == "status":
            status_key = str(val).strip().lower()
            if status_key not in VALID_TASK_STATUSES:
                raise ValueError(
                    f"status must be one of: {', '.join(sorted(VALID_TASK_STATUSES))}"
                )
            updates[key] = status_key
        elif key == "category":
            cat = str(val).strip().lower()
            if cat not in VALID_TASK_CATEGORIES:
                raise ValueError(
                    f"category must be one of: {', '.join(sorted(VALID_TASK_CATEGORIES))}"
                )
            updates[key] = cat
        elif key == "sort_order":
            updates[key] = int(val)
        elif key in ("task_title", "task_description", "due_date", "link_url"):
            updates[key] = str(val).strip() if isinstance(val, str) else val
        else:
            updates[key] = val

    if not updates:
        return get_task_by_id(task_id)

    if "status" in updates:
        updates["completed_at"] = (
            _now() if updates["status"] == "completed" else None
        )

    sets = ", ".join(f"{k} = ?" for k in updates)
    params = list(updates.values()) + [task_id]
    with _lock:
        with connect() as conn:
            row = conn.execute(
                "SELECT employee_email FROM onboarding_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if not row:
                return None
            conn.execute(
                f"UPDATE onboarding_tasks SET {sets} WHERE id = ?",
                params,
            )
            conn.commit()
            employee_email = row["employee_email"]

    task = get_task_by_id(task_id)
    if task:
        pending = count_pending_tasks(employee_email)
        if pending == 0:
            mark_onboarding_complete(employee_email)
        else:
            with _lock:
                with connect() as conn:
                    conn.execute(
                        """
                        UPDATE employees SET onboarding_complete = 0
                        WHERE email = ?
                        """,
                        (_email(employee_email),),
                    )
                    conn.commit()
    return task


def delete_task(task_id: str) -> bool:
    init_audit_db()
    with _lock:
        with connect() as conn:
            row = conn.execute(
                "SELECT id, employee_email FROM onboarding_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            if not row:
                return False
            conn.execute("DELETE FROM onboarding_tasks WHERE id = ?", (task_id,))
            conn.commit()
            employee_email = row["employee_email"]
    pending = count_pending_tasks(employee_email)
    if pending == 0 and count_tasks_for_employee(employee_email) > 0:
        mark_onboarding_complete(employee_email)
    return True


def delete_reminder(reminder_id: str) -> bool:
    init_audit_db()
    with _lock:
        with connect() as conn:
            cur = conn.execute(
                "DELETE FROM onboarding_reminders WHERE id = ?", (reminder_id,)
            )
            conn.commit()
            return cur.rowcount > 0


def admin_update_reminder(reminder_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    init_audit_db()
    allowed = {"reminder_type", "sent_at", "delivery_status", "channel"}
    updates: Dict[str, Any] = {}
    for key, val in fields.items():
        if key not in allowed or val is None:
            continue
        updates[key] = str(val).strip() if isinstance(val, str) else val
    if not updates:
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM onboarding_reminders WHERE id = ?", (reminder_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None
    sets = ", ".join(f"{k} = ?" for k in updates)
    params = list(updates.values()) + [reminder_id]
    with _lock:
        with connect() as conn:
            row = conn.execute(
                "SELECT id FROM onboarding_reminders WHERE id = ?", (reminder_id,)
            ).fetchone()
            if not row:
                return None
            conn.execute(
                f"UPDATE onboarding_reminders SET {sets} WHERE id = ?",
                params,
            )
            conn.commit()
            out = conn.execute(
                "SELECT * FROM onboarding_reminders WHERE id = ?", (reminder_id,)
            ).fetchone()
    return _row_to_dict(out) if out else None


def update_task_status_by_key(
    employee_email: str,
    task_key: str,
    status: str = "completed",
) -> Optional[Dict[str, Any]]:
    init_audit_db()
    email_key = _email(employee_email)
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id FROM onboarding_tasks
            WHERE employee_email = ? AND task_key = ?
            """,
            (email_key, task_key),
        ).fetchone()
    if not row:
        return None
    return update_task_status(row["id"], email_key, status)


def count_pending_tasks(email: str) -> int:
    init_audit_db()
    email_key = _email(email)
    with connect() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c FROM onboarding_tasks
            WHERE employee_email = ? AND status = 'pending'
            """,
            (email_key,),
        ).fetchone()
    return int(row["c"]) if row else 0


def increment_task_reminders(email: str, *, reminded_at: str) -> None:
    init_audit_db()
    email_key = _email(email)
    with _lock:
        with connect() as conn:
            conn.execute(
                """
                UPDATE onboarding_tasks
                SET reminder_count = reminder_count + 1,
                    last_reminded_at = ?
                WHERE employee_email = ? AND status = 'pending'
                """,
                (reminded_at, email_key),
            )
            conn.commit()


def insert_reminder(
    *,
    employee_email: str,
    reminder_type: str,
    task_id: str | None = None,
    delivery_status: str = "sent",
    channel: str = "email",
    sent_at: str | None = None,
) -> Dict[str, Any]:
    init_audit_db()
    rid = str(uuid.uuid4())
    when = sent_at or _now()
    with _lock:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO onboarding_reminders (
                    id, employee_email, task_id, reminder_type,
                    sent_at, delivery_status, channel
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rid,
                    _email(employee_email),
                    task_id,
                    reminder_type,
                    when,
                    delivery_status,
                    channel,
                ),
            )
            conn.commit()
    return {
        "id": rid,
        "employee_email": _email(employee_email),
        "task_id": task_id,
        "reminder_type": reminder_type,
        "sent_at": when,
        "delivery_status": delivery_status,
        "channel": channel,
    }


def list_reminders(email: str, limit: int = 50) -> List[Dict[str, Any]]:
    init_audit_db()
    email_key = _email(email)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM onboarding_reminders
            WHERE employee_email = ?
            ORDER BY sent_at DESC
            LIMIT ?
            """,
            (email_key, limit),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def has_reminder_today(
    employee_email: str,
    reminder_type: str,
    *,
    today: date,
) -> bool:
    init_audit_db()
    email_key = _email(employee_email)
    day_start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc).isoformat()
    day_end = datetime.combine(
        today + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc
    ).isoformat()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT id FROM onboarding_reminders
            WHERE employee_email = ?
              AND reminder_type = ?
              AND sent_at >= ?
              AND sent_at < ?
            LIMIT 1
            """,
            (email_key, reminder_type, day_start, day_end),
        ).fetchone()
    return row is not None


def list_active_onboarding_employees(
    *,
    today: date,
    window_days: int = 7,
) -> List[Dict[str, Any]]:
    init_audit_db()
    earliest = (today - timedelta(days=window_days - 1)).isoformat()
    latest = today.isoformat()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM employees
            WHERE active = 1
              AND onboarding_complete = 0
              AND joining_date >= ?
              AND joining_date <= ?
            ORDER BY joining_date ASC
            """,
            (earliest, latest),
        ).fetchall()
    return [_employee_from_row(r) for r in rows]


def onboarding_day(joining_date: str, today: date) -> int:
    joined = date.fromisoformat(joining_date)
    return (today - joined).days + 1


def get_onboarding_overview(*, today: date | None = None) -> Dict[str, Any]:
    init_audit_db()
    today = today or date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    employees = list_employees(onboarding_complete=False)
    all_employees = list_employees()

    new_hires = [
        e
        for e in all_employees
        if e.get("joining_date", "") >= week_start
        and e.get("joining_date", "") <= today.isoformat()
    ]

    completion_rates: List[Dict[str, Any]] = []
    pending_by_category: Dict[str, int] = {}
    employees_needing_followup: List[Dict[str, Any]] = []

    for emp in employees:
        if not emp.get("active"):
            continue
        tasks = get_tasks(emp["email"])
        total = len(tasks)
        completed = sum(1 for t in tasks if t.get("status") == "completed")
        pct = round(100 * completed / total, 1) if total else 0.0
        completion_rates.append(
            {
                "email": emp["email"],
                "name": emp["full_name"],
                "joining_date": emp["joining_date"],
                "completed": completed,
                "total": total,
                "percentage": pct,
            }
        )
        for t in tasks:
            if t.get("status") == "pending":
                cat = t.get("category") or "other"
                pending_by_category[cat] = pending_by_category.get(cat, 0) + 1
        day = onboarding_day(emp["joining_date"], today)
        if day >= 5 and completed < total:
            employees_needing_followup.append(
                {
                    "email": emp["email"],
                    "name": emp["full_name"],
                    "joining_date": emp["joining_date"],
                    "onboarding_day": day,
                    "completed": completed,
                    "total": total,
                    "percentage": pct,
                }
            )

    return {
        "new_hires_this_week": len(new_hires),
        "completion_rates": completion_rates,
        "pending_by_category": pending_by_category,
        "employees_needing_followup": employees_needing_followup,
    }


def get_employee_detail(email: str) -> Optional[Dict[str, Any]]:
    emp = get_employee(email)
    if not emp:
        return None
    tasks = get_tasks(email)
    reminders = list_reminders(email)
    total = len(tasks)
    completed = sum(1 for t in tasks if t.get("status") == "completed")
    return {
        "employee": emp,
        "tasks": tasks,
        "reminders": reminders,
        "completed": completed,
        "total": total,
        "percentage": round(100 * completed / total, 1) if total else 0.0,
    }


def tasks_grouped_by_category(tasks: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for t in tasks:
        cat = t.get("category") or "other"
        grouped.setdefault(cat, []).append(t)
    return grouped
