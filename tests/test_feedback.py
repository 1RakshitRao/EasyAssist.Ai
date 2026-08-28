"""Tests for answer like/dislike feedback API."""

from __future__ import annotations

import json


def _post_feedback(client, headers, **overrides):
    payload = {
        "message_id": "msg-1",
        "session_id": "sess-1",
        "question": "How do I reset my VPN password?",
        "answer": "Open the Ampcus VPN portal and click Forgot password.",
        "rating": "up",
        "department": "it",
        "sources": ["vpn-faq"],
    }
    payload.update(overrides)
    return client.post("/feedback", headers=headers, json=payload)


def test_employee_can_like_and_upsert(client, employee_headers):
    res = _post_feedback(client, employee_headers, rating="up")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["rating"] == "up"
    assert body["status"] == "open"
    assert body["message_id"] == "msg-1"

    res2 = _post_feedback(
        client,
        employee_headers,
        rating="down",
        comment="Missing MFA steps",
        corrected_answer="Reset via portal, then complete MFA on the authenticator app.",
    )
    assert res2.status_code == 200, res2.text
    body2 = res2.json()
    assert body2["id"] == body["id"]
    assert body2["rating"] == "down"
    assert body2["comment"] == "Missing MFA steps"
    assert "authenticator" in (body2["corrected_answer"] or "")


def test_employee_cannot_list_or_apply(client, employee_headers):
    created = _post_feedback(
        client,
        employee_headers,
        rating="down",
        comment="Wrong dept",
        corrected_answer="Corrected VPN reset steps for Windows.",
    )
    assert created.status_code == 200
    fid = created.json()["id"]

    listed = client.get("/feedback", headers=employee_headers)
    assert listed.status_code == 403

    applied = client.post(
        f"/feedback/{fid}/apply-kb",
        headers=employee_headers,
        json={"department": "it"},
    )
    assert applied.status_code == 403

    exported = client.get("/feedback/export", headers=employee_headers)
    assert exported.status_code == 403


def test_agent_list_apply_dismiss(client, agent_headers, employee_headers):
    created = _post_feedback(
        client,
        employee_headers,
        message_id="msg-apply",
        rating="down",
        comment="Incomplete",
        corrected_answer="Use the Ampcus VPN self-service portal, then sign in with MFA.",
        department="it",
    )
    assert created.status_code == 200, created.text
    fid = created.json()["id"]

    listed = client.get(
        "/feedback?rating=down&status=open",
        headers=agent_headers,
    )
    assert listed.status_code == 200, listed.text
    ids = {row["id"] for row in listed.json()}
    assert fid in ids

    applied = client.post(
        f"/feedback/{fid}/apply-kb",
        headers=agent_headers,
        json={"department": "it"},
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["status"] == "applied"
    assert body["kb_doc_id"]
    assert body["feedback"]["status"] == "applied"

    again = client.post(
        f"/feedback/{fid}/apply-kb",
        headers=agent_headers,
        json={"department": "it"},
    )
    assert again.status_code == 400

    created2 = _post_feedback(
        client,
        employee_headers,
        message_id="msg-dismiss",
        rating="down",
        comment="Noise",
    )
    assert created2.status_code == 200
    fid2 = created2.json()["id"]
    dismissed = client.post(
        f"/feedback/{fid2}/dismiss",
        headers=agent_headers,
    )
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["status"] == "dismissed"


def test_admin_export_jsonl(client, admin_headers, employee_headers):
    _post_feedback(client, employee_headers, message_id="msg-up", rating="up")
    _post_feedback(
        client,
        employee_headers,
        message_id="msg-down",
        rating="down",
        comment="Bad",
        corrected_answer="Better answer text for training.",
    )

    res = client.get("/feedback/export", headers=admin_headers)
    assert res.status_code == 200, res.text
    assert "application/x-ndjson" in res.headers.get("content-type", "")
    lines = [ln for ln in res.text.strip().splitlines() if ln.strip()]
    assert len(lines) >= 2
    parsed = [json.loads(ln) for ln in lines]
    ratings = {row["rating"] for row in parsed}
    assert "up" in ratings
    assert "down" in ratings
    down = next(row for row in parsed if row["rating"] == "down")
    assert down["rejected"]
    assert down["chosen"]
    assert down["prompt"]


def test_mine_feedback_for_session(client, employee_headers):
    _post_feedback(
        client,
        employee_headers,
        message_id="msg-s1",
        session_id="session-abc",
        rating="up",
    )
    _post_feedback(
        client,
        employee_headers,
        message_id="msg-s2",
        session_id="session-abc",
        rating="down",
        comment="Nope",
    )
    res = client.get(
        "/feedback/mine?session_id=session-abc",
        headers=employee_headers,
    )
    assert res.status_code == 200, res.text
    rows = res.json()
    assert len(rows) == 2
    assert {r["message_id"] for r in rows} == {"msg-s1", "msg-s2"}


def test_invalid_rating_rejected(client, employee_headers):
    res = _post_feedback(client, employee_headers, rating="meh")
    assert res.status_code == 400
