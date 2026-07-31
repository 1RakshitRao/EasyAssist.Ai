"""Integration tests for audit logging, restriction gate, admin insights."""

from __future__ import annotations

from datetime import datetime, timezone

from app.audit.enforcement import create_training_token
from app.audit.store import list_user_queries
from app.auth.users import set_access_restricted


def test_query_writes_audit_row(client, employee_headers):
    res = client.post(
        "/query",
        headers=employee_headers,
        json={"question": "How do I reset my VPN password after an MFA error?"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert "prompt_score" in body
    assert body["prompt_score"] is not None
    rows = list_user_queries("employee@ampcus.com", limit=5)
    assert rows
    assert rows[0]["query"]
    assert rows[0]["prompt_score"] is not None
    assert rows[0]["user_email"] == "employee@ampcus.com"


def test_restricted_user_blocked(client, employee_headers):
    set_access_restricted("employee@ampcus.com", True)
    res = client.post(
        "/query",
        headers=employee_headers,
        json={"question": "How do I reset VPN?"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["model_used"] == "training_gate"
    assert "training" in body["answer"].lower()
    rows = list_user_queries("employee@ampcus.com", limit=5)
    assert any(r["intent"] == "restricted" for r in rows)


def test_admin_insights_forbidden_for_employee(client, employee_headers):
    res = client.get("/admin/insights", headers=employee_headers)
    assert res.status_code == 403


def test_admin_insights_ok(client, admin_headers, employee_headers):
    client.post(
        "/query",
        headers=employee_headers,
        json={"question": "What is the PTO accrual policy for full-time employees?"},
    )
    res = client.get("/admin/insights", headers=admin_headers)
    assert res.status_code == 200, res.text
    data = res.json()
    assert "users" in data
    assert data["total_queries"] >= 1
    emails = [u["user_email"] for u in data["users"]]
    assert "employee@ampcus.com" in emails


def test_training_complete_lifts_flag(client, employee_headers, admin_headers):
    set_access_restricted("employee@ampcus.com", True)
    from app.audit.store import upsert_training

    upsert_training(
        "employee@ampcus.com",
        access_restricted=True,
        warning_sent_at=datetime.now(timezone.utc).isoformat(),
    )
    token = create_training_token("employee@ampcus.com")
    res = client.post("/auth/training/complete", json={"token": token})
    assert res.status_code == 200, res.text
    me = client.get("/auth/me", headers=employee_headers)
    assert me.status_code == 200
    assert me.json()["access_restricted"] is False

    # Also admin path
    set_access_restricted("employee@ampcus.com", True)
    upsert_training("employee@ampcus.com", access_restricted=True)
    admin = client.post(
        "/admin/users/employee@ampcus.com/training-complete",
        headers=admin_headers,
    )
    assert admin.status_code == 200
    me2 = client.get("/auth/me", headers=employee_headers)
    assert me2.json()["access_restricted"] is False


def test_admin_user_queries_drilldown(client, admin_headers, employee_headers):
    client.post(
        "/query",
        headers=employee_headers,
        json={"question": "How do I connect to corporate wifi on my laptop?"},
    )
    res = client.get(
        "/admin/users/employee@ampcus.com/queries?limit=10",
        headers=admin_headers,
    )
    assert res.status_code == 200
    assert res.json()["queries"]
