"""API / pipeline integration tests — no live Grok/Anthropic required."""

from __future__ import annotations


def test_health_and_home(client):
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["chroma_collections"]["hr"] >= 1
    assert body["chroma_collections"]["it"] >= 1
    assert body["chroma_collections"]["compliance"] >= 1
    assert body["chroma_collections"]["legal"] >= 1

    home = client.get("/")
    assert home.status_code == 200
    assert b"Ampcus" in home.content


def test_kb_lists_department_protocols(client, admin_headers):
    res = client.get("/kb", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total_documents"] >= 32
    depts = {d["department"]: d for d in data["departments"]}
    assert set(depts) == {"hr", "it", "compliance", "legal"}
    assert any(doc["title"] == "PTO Accrual Policy" for doc in depts["hr"]["documents"])
    assert any(doc["title"] == "VPN Setup Guide" for doc in depts["it"]["documents"])


def test_query_hr_pto_grounded(client, admin_headers):
    res = client.post(
        "/query",
        headers=admin_headers,
        json={"question": "How many PTO days do I get per year?"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["department"] == "hr"
    assert data["severity"] == "routine"
    assert data["context_used"] is True
    assert data["ticket_id"] is None
    assert data["escalated"] is False
    assert data["cached"] is False
    assert data["sources"]
    assert "20" in data["answer"] or "PTO" in data["answer"] or "paid time" in data["answer"].lower()


def test_query_it_password_and_semantic_cache(client, admin_headers):
    q = "How do I reset my password?"
    first = client.post("/query", headers=admin_headers, json={"question": q})
    assert first.status_code == 200
    a = first.json()
    assert a["department"] == "it"
    assert a["context_used"] is True
    assert a["cached"] is False

    second = client.post("/query", headers=admin_headers, json={"question": q})
    assert second.status_code == 200
    b = second.json()
    assert b["cached"] is True
    assert b["department"] == "it"
    assert b["answer"] == a["answer"]


def test_query_unknown_creates_ticket(client, admin_headers):
    res = client.post(
        "/query",
        headers=admin_headers,
        json={"question": "What is the cafeteria sushi menu this Friday?"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["department"] == "unknown"
    assert data["pending_ticket_confirmation"] is True
    assert data["ticket_id"] is None
    assert data["model_used"] == "no_context"
    assert data["context_used"] is False
    assert "support ticket" in data["answer"].lower()

    confirm = client.post(
        "/query",
        headers=admin_headers,
        json={
            "question": "(confirm)",
            "confirm_ticket": True,
            "session_id": data["session_id"],
        },
    )
    assert confirm.status_code == 200
    confirmed = confirm.json()
    assert confirmed["ticket_id"]
    assert confirmed["model_used"] == "hitl_ticket"
    assert confirmed["pending_ticket_confirmation"] is False

    tickets = client.get(
        "/tickets",
        headers=admin_headers,
        params={"status": "open", "ticket_type": "unknown"},
    )
    assert tickets.status_code == 200
    items = tickets.json()
    assert any(t["id"] == confirmed["ticket_id"] for t in items)
    match = next(t for t in items if t["id"] == confirmed["ticket_id"])
    assert match["reason"] == "kb_not_recognized"


def test_query_high_severity_escalation(client, admin_headers):
    res = client.post(
        "/query",
        headers=admin_headers,
        json={"question": "I think we had a customer data breach — what should I do?"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["department"] == "legal"
    assert data["severity"] == "high"
    assert data["escalated"] is True
    assert data["pending_ticket_confirmation"] is True
    assert data["ticket_id"] is None
    assert data["context_used"] is True

    confirm = client.post(
        "/query",
        headers=admin_headers,
        json={
            "question": "(confirm)",
            "confirm_ticket": True,
            "session_id": data["session_id"],
        },
    )
    assert confirm.status_code == 200
    confirmed = confirm.json()
    assert confirmed["ticket_id"]
    assert confirmed["escalated"] is True

    esc = client.get(
        "/tickets",
        headers=admin_headers,
        params={"status": "open", "ticket_type": "escalation"},
    )
    assert esc.status_code == 200
    assert any(t["id"] == confirmed["ticket_id"] for t in esc.json())


def test_ingest_unique_then_dedup_conflict(client, admin_headers):
    unique = client.post(
        "/ingest",
        headers=admin_headers,
        json={
            "department": "hr",
            "title": "Desk Hoteling Pilot Rules",
            "content": "Reserve desks weekly in the facilities portal before 5pm Friday.",
        },
    )
    assert unique.status_code == 200
    assert unique.json()["status"] == "ok"
    doc_id = unique.json()["doc_id"]

    dup_title = client.post(
        "/ingest",
        headers=admin_headers,
        json={
            "department": "hr",
            "title": "desk hoteling pilot rules",
            "content": "Totally different body text that should still collide on title.",
        },
    )
    assert dup_title.status_code == 409
    detail = dup_title.json()["detail"]
    assert detail["duplicate_of"] == doc_id
    assert detail["reason"] == "exact_title"

    near = client.post(
        "/ingest",
        headers=admin_headers,
        json={
            "department": "hr",
            "title": "Paid Time Off Yearly Accrual",
            "content": (
                "Full-time employees accrue 20 days of paid time off (PTO) per calendar year. "
                "Accrual begins on the hire date at a rate of 1.67 days per month."
            ),
        },
    )
    assert near.status_code == 409
    assert near.json()["detail"]["reason"] in {"embedding_near_duplicate", "exact_title"}


def test_promote_unknown_ticket_into_kb(client, admin_headers):
    from tests.conftest import confirm_pending_ticket

    q = client.post(
        "/query",
        headers=admin_headers,
        json={"question": "Where do I park my electric scooter overnight?"},
    )
    assert q.status_code == 200
    assert q.json()["pending_ticket_confirmation"] is True
    ticket_id = confirm_pending_ticket(client, admin_headers, q.json())["ticket_id"]

    promote = client.post(
        f"/tickets/{ticket_id}/promote",
        headers=admin_headers,
        json={
            "department": "it",
            "title": "Electric Scooter Parking",
            "answer": "Park scooters in the garage rack on B1 and register the serial in the IT portal.",
        },
    )
    assert promote.status_code == 200
    body = promote.json()
    assert body["status"] == "resolved"
    assert body["kb_doc_id"]
    assert body["assigned_department"] == "it"

    open_unknown = client.get(
        "/tickets",
        headers=admin_headers,
        params={"status": "open", "ticket_type": "unknown"},
    )
    assert ticket_id not in {t["id"] for t in open_unknown.json()}

    kb = client.get("/kb", headers=admin_headers, params={"department": "it"})
    titles = [d["title"] for d in kb.json()["departments"][0]["documents"]]
    assert "Electric Scooter Parking" in titles


def test_resolve_escalation_ticket(client, admin_headers):
    from tests.conftest import confirm_pending_ticket

    q = client.post(
        "/query",
        headers=admin_headers,
        json={"question": "I need to report workplace harassment immediately"},
    )
    assert q.status_code == 200
    data = q.json()
    assert data["escalated"] is True
    assert data["pending_ticket_confirmation"] is True
    ticket_id = confirm_pending_ticket(client, admin_headers, data)["ticket_id"]

    resolved = client.patch(
        f"/tickets/{ticket_id}/resolve",
        headers=admin_headers,
        json={"status": "resolved", "admin_notes": "HR case opened"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"

    open_esc = client.get(
        "/tickets",
        headers=admin_headers,
        params={"status": "open", "ticket_type": "escalation"},
    )
    assert ticket_id not in {t["id"] for t in open_esc.json()}


def test_stats_and_reset_session(client, admin_headers):
    client.post(
        "/query",
        headers=admin_headers,
        json={"question": "How many PTO days do I get per year?"},
    )
    stats = client.get("/stats", headers=admin_headers)
    assert stats.status_code == 200
    assert stats.json()["total_queries"] >= 1
    assert stats.json()["recent"]

    reset = client.post("/stats/reset", headers=admin_headers)
    assert reset.status_code == 200
    assert reset.json()["status"] == "ok"
    assert reset.json()["stats"]["total_queries"] == 0
    assert reset.json()["stats"]["recent"] == []
