"""Office printer registry — IPP endpoints per office location."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.audit.db import connect, init_audit_db

logger = logging.getLogger(__name__)
_lock = threading.Lock()

_SEED_PRINTERS: List[Dict[str, Any]] = [
    {
        "office_location": "Ampcus Office",
        "printer_name": "TOSHIBA e-STUDIO3505AC-11965425",
        "printer_ip": "10.1.0.22",
        "ipp_port": 50081,
        "ipp_path": "/ipp/print",
        "model": "Toshiba e-STUDIO3505AC",
        "floor": "4th",
        "notes": "Microsoft IPP Class Driver · color · duplex · staple · 35 ppm",
    },
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_office(office: str) -> str:
    return " ".join((office or "").strip().split()).lower()


def _row_to_dict(row) -> Dict[str, Any]:
    return dict(row) if row else {}


def seed_office_printers_if_empty() -> None:
    init_audit_db()
    with _lock:
        with connect() as conn:
            count = conn.execute("SELECT COUNT(*) AS c FROM office_printers").fetchone()["c"]
            if count:
                _sync_known_printers(conn)
                conn.commit()
                return
            for p in _SEED_PRINTERS:
                conn.execute(
                    """
                    INSERT INTO office_printers (
                        id, office_location, printer_name, printer_ip,
                        ipp_port, ipp_path, model, floor, notes, active, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        p["office_location"],
                        p["printer_name"],
                        p["printer_ip"],
                        int(p.get("ipp_port") or 631),
                        p.get("ipp_path") or "/ipp/print",
                        p.get("model"),
                        p.get("floor"),
                        p.get("notes"),
                        _now_iso(),
                    ),
                )
            conn.commit()
    logger.info("Seeded %d office printers", len(_SEED_PRINTERS))


def _sync_known_printers(conn) -> None:
    """Update the default printer and deactivate legacy multi-site entries."""
    p = _SEED_PRINTERS[0]
    primary_office = _normalize_office(p["office_location"])

    row = conn.execute(
        """
        SELECT id FROM office_printers
        WHERE active = 1
        ORDER BY created_at ASC
        LIMIT 1
        """
    ).fetchone()

    if row:
        conn.execute(
            """
            UPDATE office_printers SET
                office_location = ?, printer_name = ?, printer_ip = ?, ipp_port = ?,
                ipp_path = ?, model = ?, floor = ?, notes = ?
            WHERE id = ?
            """,
            (
                p["office_location"],
                p["printer_name"],
                p["printer_ip"],
                int(p.get("ipp_port") or 631),
                p.get("ipp_path") or "/ipp/print",
                p.get("model"),
                p.get("floor"),
                p.get("notes"),
                row["id"],
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO office_printers (
                id, office_location, printer_name, printer_ip,
                ipp_port, ipp_path, model, floor, notes, active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (
                str(uuid.uuid4()),
                p["office_location"],
                p["printer_name"],
                p["printer_ip"],
                int(p.get("ipp_port") or 631),
                p.get("ipp_path") or "/ipp/print",
                p.get("model"),
                p.get("floor"),
                p.get("notes"),
                _now_iso(),
            ),
        )

    conn.execute(
        """
        UPDATE office_printers SET active = 0
        WHERE active = 1 AND LOWER(office_location) != ?
        """,
        (primary_office,),
    )
    logger.info("Synced default printer ip=%s port=%s", p["printer_ip"], p.get("ipp_port"))


def list_printers(*, active_only: bool = True) -> List[Dict[str, Any]]:
    init_audit_db()
    sql = "SELECT * FROM office_printers"
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY office_location, printer_name"
    with connect() as conn:
        rows = conn.execute(sql).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_printer(printer_id: str) -> Optional[Dict[str, Any]]:
    init_audit_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM office_printers WHERE id = ?",
            (printer_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_default_printer() -> Optional[Dict[str, Any]]:
    """Return the single office printer (all employees share one site)."""
    init_audit_db()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM office_printers
            WHERE active = 1
            ORDER BY created_at ASC
            LIMIT 1
            """
        ).fetchone()
    return _row_to_dict(row) if row else None


def get_printer_for_office(office_location: str) -> Optional[Dict[str, Any]]:
    """Legacy alias — returns default printer regardless of office."""
    return get_default_printer()


def list_office_locations() -> List[str]:
    return sorted({p["office_location"] for p in list_printers()})


def create_printer(
    *,
    office_location: str,
    printer_name: str,
    printer_ip: str,
    ipp_port: int = 631,
    ipp_path: str = "/ipp/print",
    model: str | None = None,
    floor: str | None = None,
    notes: str | None = None,
) -> Dict[str, Any]:
    init_audit_db()
    pid = str(uuid.uuid4())
    with _lock:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO office_printers (
                    id, office_location, printer_name, printer_ip,
                    ipp_port, ipp_path, model, floor, notes, active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    pid,
                    office_location.strip(),
                    printer_name.strip(),
                    printer_ip.strip(),
                    int(ipp_port),
                    (ipp_path or "/ipp/print").strip(),
                    (model or "").strip() or None,
                    (floor or "").strip() or None,
                    (notes or "").strip() or None,
                    _now_iso(),
                ),
            )
            conn.commit()
    return get_printer(pid) or {}


def delete_printer(printer_id: str) -> bool:
    init_audit_db()
    with _lock:
        with connect() as conn:
            cur = conn.execute(
                "UPDATE office_printers SET active = 0 WHERE id = ?",
                (printer_id,),
            )
            conn.commit()
            return cur.rowcount > 0


def seed_conference_rooms_if_empty() -> None:
    """Local cache of conference rooms when Graph is unavailable."""
    init_audit_db()
    seed_rows = [
        ("Ampcus Office", "Conference Room A", "room-a@ampcus.com", 12, "4th", '["Teams Room","HDMI"]'),
        ("Ampcus Office", "Conference Room B", "room-b@ampcus.com", 6, "4th", '["HDMI display"]'),
        ("Ampcus Office", "Conference Room C", "room-c@ampcus.com", 20, "4th", '["Teams Room","video conferencing"]'),
    ]
    with _lock:
        with connect() as conn:
            count = conn.execute("SELECT COUNT(*) AS c FROM conference_rooms").fetchone()["c"]
            if count:
                return
            for office, name, email, cap, floor, av in seed_rows:
                conn.execute(
                    """
                    INSERT INTO conference_rooms (
                        id, office_location, room_name, room_email,
                        capacity, floor, av_equipment_json, active, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                    """,
                    (str(uuid.uuid4()), office, name, email, cap, floor, av, _now_iso()),
                )
            conn.commit()
    logger.info("Seeded %d conference rooms", len(seed_rows))


def list_conference_rooms(*, office_location: str | None = None) -> List[Dict[str, Any]]:
    init_audit_db()
    sql = "SELECT * FROM conference_rooms WHERE active = 1"
    params: list = []
    if office_location:
        sql += " AND LOWER(office_location) = ?"
        params.append(_normalize_office(office_location))
    sql += " ORDER BY office_location, room_name"
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(r) for r in rows]
