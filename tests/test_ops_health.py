"""Operations Health aggregation tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.analytics.ops_health import compute_ops_health


def test_ops_health_kpis(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    from app.config import get_settings
    import app.analytics.ops_health as ops_mod

    get_settings.cache_clear()
    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)

    def _mk(tid, status, created_days_ago, resolved_hours=None, severity="routine", dept="it"):
        created = now - timedelta(days=created_days_ago)
        ticket = {
            "id": tid,
            "question": f"Q {tid}",
            "normalized_query": f"q {tid}",
            "ticket_type": "unknown",
            "department": dept,
            "severity": severity,
            "status": status,
            "reason": "test",
            "attempted_depts": [],
            "created_at": created.isoformat(),
            "updated_at": created.isoformat(),
            "assigned_department": dept if status != "open" else None,
            "kb_doc_id": None,
            "admin_notes": None,
            "created_by_user_id": "u1",
            "created_by_email": "emp@ampcus.com",
            "updated_by_user_id": "admin",
            "updated_by_email": "admin@ampcus.com",
            "resolved_at": None,
        }
        if status == "resolved" and resolved_hours is not None:
            end = created + timedelta(hours=resolved_hours)
            ticket["resolved_at"] = end.isoformat()
            ticket["updated_at"] = end.isoformat()
        return ticket

    tickets = [
        _mk("a", "open", 1),
        _mk("b", "assigned", 2, dept="hr"),
        _mk("c", "resolved", 5, resolved_hours=6, severity="high", dept="legal"),
        _mk("d", "resolved", 10, resolved_hours=30, dept="compliance"),
    ]
    monkeypatch.setattr(ops_mod, "list_tickets", lambda **kwargs: tickets)

    ops = compute_ops_health(now=now)
    assert ops["kpis"]["open_tickets"] == 2
    assert ops["kpis"]["created_last_30d"] == 4
    assert ops["kpis"]["resolved_last_30d"] == 2
    assert ops["kpis"]["avg_resolution_hours"] == 18.0
    assert ops["kpis"]["mttr_hours"] == 18.0
    # one of two resolved within 24h SLA
    assert ops["kpis"]["sla_compliance_pct"] == 50.0
    assert ops["health"]["score"] is not None
    assert ops["insights"]["aging"]["0-1d"] + ops["insights"]["aging"]["1-3d"] == 2
    assert len(ops["trends"]["created_vs_resolved_90d"]) == 90
    assert len(ops["sparklines"]["created"]) == 14
    assert len(ops["timeline"]) == 2

    get_settings.cache_clear()
