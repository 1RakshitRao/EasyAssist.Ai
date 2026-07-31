"""Operations Health metrics derived from persistent HITL tickets."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.tickets.store import list_tickets


def _parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _day_key(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).date().isoformat()


def _week_key(dt: datetime) -> str:
    iso = dt.astimezone(timezone.utc).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _resolution_end(ticket: Dict[str, Any]) -> Optional[datetime]:
    if (ticket.get("status") or "").lower() != "resolved":
        return None
    return _parse_ts(ticket.get("resolved_at")) or _parse_ts(ticket.get("updated_at"))


def _duration_hours(start: Optional[datetime], end: Optional[datetime]) -> Optional[float]:
    if not start or not end:
        return None
    secs = (end - start).total_seconds()
    if secs < 0:
        return None
    return secs / 3600.0


def _empty_day_series(days: int, now: datetime) -> List[str]:
    start = (now - timedelta(days=days - 1)).date()
    return [(start + timedelta(days=i)).isoformat() for i in range(days)]


def _pct_delta(current: float, previous: float) -> Optional[float]:
    if previous == 0:
        return 100.0 if current > 0 else (0.0 if current == 0 else None)
    return round(100.0 * (current - previous) / previous, 1)


def _count_in_window(
    tickets: List[Dict[str, Any]],
    *,
    start: datetime,
    end: datetime,
    mode: str,
) -> int:
    n = 0
    for t in tickets:
        if mode == "created":
            ts = _parse_ts(t.get("created_at"))
        else:
            ts = _resolution_end(t)
        if ts and start <= ts < end:
            n += 1
    return n


def _health_score(
    *,
    open_count: int,
    high_open: int,
    sla_pct: Optional[float],
    mttr_h: Optional[float],
    aging_old: int,
) -> Dict[str, Any]:
    score = 100.0
    if sla_pct is not None:
        if sla_pct < 50:
            score -= 30
        elif sla_pct < 70:
            score -= 18
        elif sla_pct < 90:
            score -= 8
    else:
        score -= 5
    if open_count > 10:
        score -= 20
    elif open_count > 5:
        score -= 10
    elif open_count > 2:
        score -= 4
    score -= min(25, high_open * 8)
    if mttr_h is not None:
        if mttr_h > 72:
            score -= 20
        elif mttr_h > 48:
            score -= 12
        elif mttr_h > 24:
            score -= 6
    score -= min(15, aging_old * 5)
    score = max(0, min(100, round(score)))
    if score >= 80:
        status, tone = "Healthy", "good"
    elif score >= 60:
        status, tone = "Watch", "warn"
    else:
        status, tone = "Critical", "bad"
    return {"score": score, "status": status, "tone": tone}


def compute_ops_health(*, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Aggregate ticket ops KPIs, trends, and insight breakdowns."""
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)

    settings = get_settings()
    sla_hours = float(getattr(settings, "ops_sla_hours", 24.0) or 24.0)
    tickets = list_tickets()

    open_like = [t for t in tickets if (t.get("status") or "") in {"open", "assigned"}]
    open_only = [t for t in tickets if (t.get("status") or "") == "open"]
    assigned = [t for t in tickets if (t.get("status") or "") == "assigned"]
    resolved = [t for t in tickets if (t.get("status") or "") == "resolved"]
    high_open = sum(
        1 for t in open_like if (t.get("severity") or "").lower() == "high"
    )

    cutoff_30 = clock - timedelta(days=30)
    cutoff_90 = clock - timedelta(days=90)
    week_ago = clock - timedelta(days=7)
    two_weeks_ago = clock - timedelta(days=14)
    today_start = clock.replace(hour=0, minute=0, second=0, microsecond=0)

    created_30 = [
        t for t in tickets if (c := _parse_ts(t.get("created_at"))) and c >= cutoff_30
    ]
    resolved_30 = [
        t for t in resolved if (e := _resolution_end(t)) and e >= cutoff_30
    ]

    created_this_week = _count_in_window(
        tickets, start=week_ago, end=clock, mode="created"
    )
    created_prev_week = _count_in_window(
        tickets, start=two_weeks_ago, end=week_ago, mode="created"
    )
    resolved_this_week = _count_in_window(
        tickets, start=week_ago, end=clock, mode="resolved"
    )
    resolved_prev_week = _count_in_window(
        tickets, start=two_weeks_ago, end=week_ago, mode="resolved"
    )
    resolved_today = _count_in_window(
        tickets, start=today_start, end=clock, mode="resolved"
    )
    created_today = _count_in_window(
        tickets, start=today_start, end=clock, mode="created"
    )

    resolve_hours: List[float] = []
    within_sla = 0
    for t in resolved_30:
        start = _parse_ts(t.get("created_at"))
        end = _resolution_end(t)
        hours = _duration_hours(start, end)
        if hours is None:
            continue
        resolve_hours.append(hours)
        if hours <= sla_hours:
            within_sla += 1

    avg_resolution_h = (
        round(sum(resolve_hours) / len(resolve_hours), 2) if resolve_hours else None
    )
    mttr_h = avg_resolution_h
    sla_pct = (
        round(100.0 * within_sla / len(resolve_hours), 1) if resolve_hours else None
    )

    days_90 = _empty_day_series(90, clock)
    days_14 = _empty_day_series(14, clock)
    created_by_day: Counter[str] = Counter()
    resolved_by_day: Counter[str] = Counter()
    for t in tickets:
        c = _parse_ts(t.get("created_at"))
        if c and c >= cutoff_90:
            created_by_day[_day_key(c)] += 1
        e = _resolution_end(t)
        if e and e >= cutoff_90:
            resolved_by_day[_day_key(e)] += 1

    baseline_open = 0
    for t in tickets:
        c = _parse_ts(t.get("created_at"))
        if not c or c >= cutoff_90:
            continue
        e = _resolution_end(t)
        if (t.get("status") or "") != "resolved" or not e or e >= cutoff_90:
            baseline_open += 1

    created_vs_resolved = []
    backlog_trend = []
    running = baseline_open
    for day in days_90:
        c = created_by_day.get(day, 0)
        r = resolved_by_day.get(day, 0)
        running = max(0, running + c - r)
        created_vs_resolved.append({"date": day, "created": c, "resolved": r})
        backlog_trend.append({"date": day, "backlog": running})

    spark_created = [created_by_day.get(d, 0) for d in days_14]
    spark_resolved = [resolved_by_day.get(d, 0) for d in days_14]
    spark_backlog = [row["backlog"] for row in backlog_trend[-14:]]

    week_created: Counter[str] = Counter()
    week_resolved: Counter[str] = Counter()
    for t in tickets:
        c = _parse_ts(t.get("created_at"))
        if c and c >= cutoff_90:
            week_created[_week_key(c)] += 1
        e = _resolution_end(t)
        if e and e >= cutoff_90:
            week_resolved[_week_key(e)] += 1
    week_keys = sorted(set(week_created) | set(week_resolved))[-12:]
    throughput_weekly = [
        {
            "week": w,
            "created": week_created.get(w, 0),
            "resolved": week_resolved.get(w, 0),
        }
        for w in week_keys
    ]

    week_hours: Dict[str, List[float]] = defaultdict(list)
    for t in resolved:
        start = _parse_ts(t.get("created_at"))
        end = _resolution_end(t)
        hours = _duration_hours(start, end)
        if hours is None or not end or end < cutoff_90:
            continue
        week_hours[_week_key(end)].append(hours)
    resolution_time_trend = [
        {
            "week": w,
            "avg_hours": round(sum(week_hours[w]) / len(week_hours[w]), 2),
            "count": len(week_hours[w]),
        }
        for w in sorted(week_hours.keys())[-12:]
    ]

    aging = {"0-1d": 0, "1-3d": 0, "3-7d": 0, "7-14d": 0, "14d+": 0}
    aging_tickets: List[Dict[str, Any]] = []
    for t in open_like:
        created = _parse_ts(t.get("created_at"))
        age_h = _duration_hours(created, clock) or 0.0
        age_d = age_h / 24.0
        if age_d < 1:
            bucket = "0-1d"
        elif age_d < 3:
            bucket = "1-3d"
        elif age_d < 7:
            bucket = "3-7d"
        elif age_d < 14:
            bucket = "7-14d"
        else:
            bucket = "14d+"
        aging[bucket] += 1
        who = (
            t.get("updated_by_email")
            or t.get("assigned_department")
            or t.get("department")
            or "Unassigned"
        )
        aging_tickets.append(
            {
                "id": t.get("id"),
                "key": f"{'ESC' if t.get('ticket_type') == 'escalation' else 'UNK'}-"
                f"{str(t.get('id') or '')[:8].upper()}",
                "question": (t.get("question") or "")[:120],
                "status": t.get("status"),
                "severity": t.get("severity"),
                "department": t.get("assigned_department") or t.get("department"),
                "owner": who,
                "age_hours": round(age_h, 1),
                "created_at": t.get("created_at"),
            }
        )
    aging_tickets.sort(key=lambda x: x.get("age_hours") or 0, reverse=True)

    by_priority = Counter((t.get("severity") or "routine").lower() for t in tickets)
    by_status = {
        "open": len(open_only),
        "assigned": len(assigned),
        "resolved": len(resolved),
    }

    by_assignee: Counter[str] = Counter()
    for t in tickets:
        if (t.get("status") or "") == "open":
            by_assignee["Unassigned"] += 1
            continue
        who = (
            t.get("updated_by_email")
            or t.get("assigned_department")
            or t.get("department")
            or "Unassigned"
        )
        by_assignee[str(who)] += 1

    by_component: Counter[str] = Counter()
    for t in tickets:
        comp = (
            t.get("assigned_department")
            or t.get("department")
            or t.get("ticket_type")
            or "unknown"
        )
        by_component[str(comp).lower()] += 1

    aging_old = aging.get("7-14d", 0) + aging.get("14d+", 0)
    health = _health_score(
        open_count=len(open_like),
        high_open=high_open,
        sla_pct=sla_pct,
        mttr_h=mttr_h,
        aging_old=aging_old,
    )

    def _counter_list(counter: Counter[str], limit: int = 12) -> List[Dict[str, Any]]:
        return [{"key": k, "count": v} for k, v in counter.most_common(limit)]

    # Activity feed: recent creates + resolves
    activity: List[Dict[str, Any]] = []
    for t in tickets:
        created = _parse_ts(t.get("created_at"))
        if created and created >= cutoff_30:
            activity.append(
                {
                    "at": created.isoformat(),
                    "kind": "opened",
                    "severity": t.get("severity"),
                    "ticket_type": t.get("ticket_type"),
                    "question": (t.get("question") or "")[:100],
                    "id": t.get("id"),
                    "key": f"{'ESC' if t.get('ticket_type') == 'escalation' else 'UNK'}-"
                    f"{str(t.get('id') or '')[:8].upper()}",
                }
            )
        end = _resolution_end(t)
        if end and end >= cutoff_30:
            activity.append(
                {
                    "at": end.isoformat(),
                    "kind": "resolved",
                    "severity": t.get("severity"),
                    "ticket_type": t.get("ticket_type"),
                    "question": (t.get("question") or "")[:100],
                    "id": t.get("id"),
                    "key": f"{'ESC' if t.get('ticket_type') == 'escalation' else 'UNK'}-"
                    f"{str(t.get('id') or '')[:8].upper()}",
                }
            )
    activity.sort(key=lambda x: x.get("at") or "", reverse=True)

    return {
        "generated_at": clock.isoformat(),
        "sla_hours": sla_hours,
        "health": health,
        "kpis": {
            "open_tickets": len(open_like),
            "open_todo": len(open_only),
            "open_in_progress": len(assigned),
            "high_open": high_open,
            "created_last_30d": len(created_30),
            "resolved_last_30d": len(resolved_30),
            "avg_resolution_hours": avg_resolution_h,
            "sla_compliance_pct": sla_pct,
            "mttr_hours": mttr_h,
            "reopened_tickets": 0,
            "total_tickets": len(tickets),
            "created_today": created_today,
            "resolved_today": resolved_today,
            "created_wow_pct": _pct_delta(created_this_week, created_prev_week),
            "resolved_wow_pct": _pct_delta(resolved_this_week, resolved_prev_week),
            "created_this_week": created_this_week,
            "resolved_this_week": resolved_this_week,
        },
        "sparklines": {
            "created": spark_created,
            "resolved": spark_resolved,
            "backlog": spark_backlog,
        },
        "trends": {
            "created_vs_resolved_90d": created_vs_resolved,
            "backlog_90d": backlog_trend,
            "throughput_weekly": throughput_weekly,
            "resolution_time_weekly": resolution_time_trend,
        },
        "insights": {
            "aging": aging,
            "aging_tickets": aging_tickets[:20],
            "by_priority": _counter_list(by_priority),
            "by_status": [{"key": k, "count": v} for k, v in by_status.items()],
            "by_assignee": _counter_list(by_assignee),
            "by_component": _counter_list(by_component),
            "reopened_tickets": 0,
        },
        "activity": activity[:40],
        "timeline": [
            {
                "id": t.get("id"),
                "question": (t.get("question") or "")[:100],
                "status": t.get("status"),
                "ticket_type": t.get("ticket_type"),
                "severity": t.get("severity"),
                "department": t.get("assigned_department") or t.get("department"),
                "created_at": t.get("created_at"),
                "resolved_at": t.get("resolved_at")
                or (t.get("updated_at") if t.get("status") == "resolved" else None),
                "resolution_hours": _duration_hours(
                    _parse_ts(t.get("created_at")), _resolution_end(t)
                ),
            }
            for t in sorted(
                resolved_30,
                key=lambda x: _resolution_end(x) or clock,
                reverse=True,
            )[:20]
        ],
    }
