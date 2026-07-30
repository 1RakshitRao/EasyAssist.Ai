"""Auth API integration — login and role matrix."""

from __future__ import annotations


def test_login_success_and_fail(client):
    bad = client.post(
        "/auth/login",
        json={"email": "admin@ampcus.com", "password": "wrong-password"},
    )
    assert bad.status_code == 401

    ok = client.post(
        "/auth/login",
        json={"email": "admin@ampcus.com", "password": "ChangeMeAdmin1!"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["access_token"]
    assert body["user"]["role"] == "admin"
    assert body["user"]["email"] == "admin@ampcus.com"

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["role"] == "admin"


def test_unauthenticated_query_is_401(client):
    res = client.post("/query", json={"question": "How many PTO days do I get?"})
    assert res.status_code == 401


def test_employee_can_query_not_tickets(client, employee_headers):
    q = client.post(
        "/query",
        headers=employee_headers,
        json={"question": "How many PTO days do I get per year?"},
    )
    assert q.status_code == 200
    assert q.json()["department"] == "hr"

    tickets = client.get(
        "/tickets",
        headers=employee_headers,
        params={"status": "open", "ticket_type": "unknown"},
    )
    assert tickets.status_code == 403

    ingest = client.post(
        "/ingest",
        headers=employee_headers,
        json={
            "department": "hr",
            "title": "Should Fail",
            "content": "Employees cannot ingest.",
        },
    )
    assert ingest.status_code == 403


def test_agent_tickets_not_ingest(client, agent_headers):
    q = client.post(
        "/query",
        headers=agent_headers,
        json={"question": "Where is the rooftop telescope stored?"},
    )
    assert q.status_code == 200
    ticket_id = q.json().get("ticket_id")
    assert ticket_id

    listed = client.get(
        "/tickets",
        headers=agent_headers,
        params={"status": "open", "ticket_type": "unknown"},
    )
    assert listed.status_code == 200
    assert any(t["id"] == ticket_id for t in listed.json())

    ingest = client.post(
        "/ingest",
        headers=agent_headers,
        json={
            "department": "it",
            "title": "Agent Cannot Ingest",
            "content": "Only admins may ingest documents.",
        },
    )
    assert ingest.status_code == 403

    reset = client.post("/stats/reset", headers=agent_headers)
    assert reset.status_code == 403


def test_admin_ingest_and_stats_reset(client, admin_headers):
    ingest = client.post(
        "/ingest",
        headers=admin_headers,
        json={
            "department": "hr",
            "title": "Auth Integration Policy",
            "content": "Admins may add unique policy documents through /ingest.",
        },
    )
    assert ingest.status_code == 200

    client.post(
        "/query",
        headers=admin_headers,
        json={"question": "How many PTO days do I get per year?"},
    )
    stats = client.get("/stats", headers=admin_headers)
    assert stats.status_code == 200
    assert stats.json()["total_queries"] >= 1

    reset = client.post("/stats/reset", headers=admin_headers)
    assert reset.status_code == 200
    assert reset.json()["stats"]["total_queries"] == 0
