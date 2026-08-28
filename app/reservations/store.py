"""Guesthouse reservation store — CRUD, availability, state machine."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.audit.db import connect, init_audit_db
from app.config import get_settings

logger = logging.getLogger(__name__)
_lock = threading.Lock()

VISIT_PURPOSES = [
    "Business travel",
    "Client meeting",
    "Training",
    "Team offsite",
    "Other",
]

STATUS_PENDING = "pending_approval"
STATUS_CONFIRMED = "confirmed"
STATUS_REJECTED = "rejected"
STATUS_CANCELLED = "cancelled"
STATUS_OVERRIDDEN = "overridden"
STATUS_COMPLETED = "completed"
STATUS_EXPIRED = "expired"

AVAIL_AVAILABLE = "available"
AVAIL_BOOKED = "booked"
AVAIL_MAINTENANCE = "maintenance"
AVAIL_BLOCKED = "blocked"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row(row) -> Optional[dict]:
    if row is None:
        return None
    return dict(row)


def _email(value: str | None) -> str:
    return (value or "").strip().lower()


def hr_contact_email() -> str:
    settings = get_settings()
    return (
        (settings.reservation_hr_email or settings.onboarding_hr_email or settings.admin_email or "")
        .strip()
        or "hr@ampcus.com"
    )


def can_modify(reservation: dict) -> Tuple[bool, str]:
    """48h cutoff for confirmed reservations only."""
    status = (reservation.get("status") or "").lower()
    if status not in (STATUS_PENDING, STATUS_CONFIRMED):
        return False, f"Cannot modify a reservation with status: {status}"
    if status == STATUS_PENDING:
        return True, ""
    checkin_d = date.fromisoformat(reservation["checkin_date"])
    hours_until = (
        datetime.combine(checkin_d, datetime.min.time(), tzinfo=timezone.utc)
        - datetime.now(timezone.utc)
    ).total_seconds() / 3600
    if hours_until <= 48:
        conf = reservation.get("confirmation_number") or reservation.get("id")
        return False, (
            "Modifications are not allowed within 48 hours of check-in. "
            f"Please contact HR at {hr_contact_email()} — reference {conf}."
        )
    return True, ""


def seed_guesthouses() -> None:
    """Insert two guesthouses × 2 rooms. Idempotent."""
    init_audit_db()
    now = _now()
    with _lock:
        with connect() as conn:
            existing = conn.execute("SELECT COUNT(*) FROM guesthouses").fetchone()[0]
            if existing >= 2:
                logger.info("Guesthouses already seeded — skipping")
                return

            guesthouses = [
                {
                    "id": str(uuid.uuid4()),
                    "name": "4656 Westfield Blvd",
                    "address": "4656 Westfield Blvd",
                    "city": "Bloomington",
                    "amenities": json.dumps(
                        ["WiFi", "Parking", "Full Kitchen", "Washer/Dryer", "Air Conditioning"]
                    ),
                    "created_at": now,
                },
                {
                    "id": str(uuid.uuid4()),
                    "name": "4050 Westfield Blvd",
                    "address": "4050 Westfield Blvd",
                    "city": "Bloomington",
                    "amenities": json.dumps(
                        ["WiFi", "Parking", "Full Kitchen", "Air Conditioning", "Workspace"]
                    ),
                    "created_at": now,
                },
            ]
            rooms_data: List[dict] = []
            for gh in guesthouses:
                conn.execute(
                    """
                    INSERT INTO guesthouses (id, name, address, city, amenities, created_at)
                    VALUES (:id, :name, :address, :city, :amenities, :created_at)
                    """,
                    gh,
                )
                for room_num in ("1", "2"):
                    rooms_data.append(
                        {
                            "id": str(uuid.uuid4()),
                            "guesthouse_id": gh["id"],
                            "room_number": room_num,
                            "room_name": f"Room {room_num}",
                            "capacity": 2,
                            "amenities": json.dumps(
                                ["Queen Bed", "Private Bathroom", "Closet", "TV"]
                            ),
                        }
                    )
            conn.executemany(
                """
                INSERT INTO rooms (id, guesthouse_id, room_number, room_name, capacity, amenities)
                VALUES (:id, :guesthouse_id, :room_number, :room_name, :capacity, :amenities)
                """,
                rooms_data,
            )
            conn.commit()
    logger.info("Seeded 2 guesthouses × 2 rooms each")


def get_all_guesthouses() -> List[dict]:
    init_audit_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT g.*, COUNT(r.id) as room_count
            FROM guesthouses g
            LEFT JOIN rooms r ON r.guesthouse_id = g.id AND r.active = 1
            WHERE g.active = 1
            GROUP BY g.id
            ORDER BY g.name
            """
        ).fetchall()
        return [_row(r) for r in rows]


def guesthouse_display_name(guesthouse_id: str) -> str:
    """Public label for UI (no street address)."""
    for i, gh in enumerate(get_all_guesthouses(), start=1):
        if gh["id"] == guesthouse_id:
            return f"Guesthouse {i}"
    return "Guesthouse"


def get_guesthouse_by_name(name: str) -> Optional[dict]:
    init_audit_db()
    key = (name or "").strip().lower()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM guesthouses WHERE active = 1 ORDER BY name"
        ).fetchall()
        for row in rows:
            if key in (row["name"] or "").lower():
                return _row(row)
    return None


def get_guesthouse_with_rooms(guesthouse_id: str) -> Optional[dict]:
    init_audit_db()
    with connect() as conn:
        gh = conn.execute(
            "SELECT * FROM guesthouses WHERE id = ? AND active = 1",
            (guesthouse_id,),
        ).fetchone()
        if not gh:
            return None
        rooms = conn.execute(
            """
            SELECT * FROM rooms WHERE guesthouse_id = ? AND active = 1
            ORDER BY room_number
            """,
            (guesthouse_id,),
        ).fetchall()
        result = _row(gh)
        result["rooms"] = [_row(r) for r in rooms]
        return result


def get_room(room_id: str) -> Optional[dict]:
    init_audit_db()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT r.*, g.name as guesthouse_name, g.address as guesthouse_address,
                   g.city as guesthouse_city, g.amenities as guesthouse_amenities
            FROM rooms r
            JOIN guesthouses g ON g.id = r.guesthouse_id
            WHERE r.id = ? AND r.active = 1
            """,
            (room_id,),
        ).fetchone()
        return _row(row) if row else None


def get_room_by_guesthouse_number(guesthouse_id: str, room_number: str) -> Optional[dict]:
    init_audit_db()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT r.*, g.name as guesthouse_name, g.address as guesthouse_address
            FROM rooms r
            JOIN guesthouses g ON g.id = r.guesthouse_id
            WHERE r.guesthouse_id = ? AND r.room_number = ? AND r.active = 1
            """,
            (guesthouse_id, str(room_number).strip()),
        ).fetchone()
        return _row(row) if row else None


def get_all_rooms() -> List[dict]:
    init_audit_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT r.*, g.name as guesthouse_name, g.address as guesthouse_address
            FROM rooms r
            JOIN guesthouses g ON g.id = r.guesthouse_id
            WHERE r.active = 1 AND g.active = 1
            ORDER BY g.name, r.room_number
            """
        ).fetchall()
        return [_row(r) for r in rows]


def _date_range(start: date, end: date, inclusive: bool = False) -> List[str]:
    result: List[str] = []
    current = start
    while (current < end) if not inclusive else (current <= end):
        result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def get_availability(
    checkin: str,
    checkout: str,
    guesthouse_id: Optional[str] = None,
    exclude_reservation_id: Optional[str] = None,
) -> List[dict]:
    init_audit_db()
    checkin_d = date.fromisoformat(checkin)
    checkout_d = date.fromisoformat(checkout)

    with connect() as conn:
        query = """
            SELECT r.id, r.room_number, r.room_name, r.capacity, r.amenities,
                   g.id as guesthouse_id, g.name as guesthouse_name,
                   g.address as guesthouse_address
            FROM rooms r
            JOIN guesthouses g ON g.id = r.guesthouse_id
            WHERE r.active = 1 AND g.active = 1
        """
        params: list = []
        if guesthouse_id:
            query += " AND g.id = ?"
            params.append(guesthouse_id)
        query += " ORDER BY g.name, r.room_number"
        rooms = conn.execute(query, params).fetchall()
        result = []
        for room in rooms:
            room_id = room["id"]
            booked_rows = conn.execute(
                """
                SELECT date, status FROM availability
                WHERE room_id = ? AND date >= ? AND date < ? AND status != 'available'
                  AND (? IS NULL OR reservation_id IS NULL OR reservation_id != ?)
                """,
                (room_id, checkin, checkout, exclude_reservation_id, exclude_reservation_id),
            ).fetchall()
            booked_dates = [r["date"] for r in booked_rows]
            result.append(
                {
                    "room_id": room_id,
                    "room_number": room["room_number"],
                    "room_name": room["room_name"],
                    "capacity": room["capacity"],
                    "amenities": json.loads(room["amenities"] or "[]"),
                    "guesthouse_id": room["guesthouse_id"],
                    "guesthouse_name": room["guesthouse_name"],
                    "guesthouse_address": room["guesthouse_address"],
                    "available": len(booked_dates) == 0,
                    "unavailable_dates": booked_dates,
                }
            )
        return result


def get_room_availability_calendar(
    room_id: str,
    from_date: str,
    to_date: str,
) -> List[dict]:
    init_audit_db()
    from_d = date.fromisoformat(from_date)
    to_d = date.fromisoformat(to_date)
    dates = _date_range(from_d, to_d, inclusive=True)

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT date, status, reservation_id FROM availability
            WHERE room_id = ? AND date >= ? AND date <= ?
            """,
            (room_id, from_date, to_date),
        ).fetchall()
        status_by_date = {r["date"]: dict(r) for r in rows}
        return [
            {
                "date": d,
                "status": status_by_date.get(d, {}).get("status", AVAIL_AVAILABLE),
                "reservation_id": status_by_date.get(d, {}).get("reservation_id"),
            }
            for d in dates
        ]


def mark_dates_booked(
    room_id: str,
    checkin: str,
    checkout: str,
    reservation_id: str,
    conn=None,
) -> None:
    checkin_d = date.fromisoformat(checkin)
    checkout_d = date.fromisoformat(checkout)
    dates = _date_range(checkin_d, checkout_d)
    now = _now()

    def _do(c):
        for d in dates:
            c.execute(
                """
                INSERT INTO availability (id, room_id, date, status,
                                          reservation_id, source, created_at)
                VALUES (?, ?, ?, 'booked', ?, 'system', ?)
                ON CONFLICT(room_id, date) DO UPDATE SET
                    status = 'booked',
                    reservation_id = excluded.reservation_id
                """,
                (str(uuid.uuid4()), room_id, d, reservation_id, now),
            )

    if conn:
        _do(conn)
    else:
        with connect() as c:
            _do(c)
            c.commit()


def mark_dates_available(
    room_id: str,
    checkin: str,
    checkout: str,
    conn=None,
) -> None:
    checkin_d = date.fromisoformat(checkin)
    checkout_d = date.fromisoformat(checkout)
    dates = _date_range(checkin_d, checkout_d)

    def _do(c):
        for d in dates:
            c.execute(
                """
                UPDATE availability SET status = 'available', reservation_id = NULL
                WHERE room_id = ? AND date = ?
                """,
                (room_id, d),
            )

    if conn:
        _do(conn)
    else:
        with connect() as c:
            _do(c)
            c.commit()


def apply_availability_status(
    room_id: str,
    day: str,
    status: str,
    *,
    uploaded_by: str | None = None,
    source: str = "excel_upload",
    conn=None,
) -> None:
    now = _now()

    def _do(c):
        c.execute(
            """
            INSERT INTO availability (id, room_id, date, status, source, uploaded_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(room_id, date) DO UPDATE SET
                status = excluded.status,
                source = excluded.source,
                uploaded_by = excluded.uploaded_by,
                reservation_id = CASE
                    WHEN excluded.status = 'available' THEN NULL
                    ELSE reservation_id
                END
            """,
            (str(uuid.uuid4()), room_id, day, status, source, uploaded_by, now),
        )

    if conn:
        _do(conn)
    else:
        with connect() as c:
            _do(c)
            c.commit()


def _generate_confirmation_number(conn) -> str:
    year = datetime.now().year
    count = conn.execute("SELECT COUNT(*) FROM reservations").fetchone()[0] + 1
    return f"GH-{year}-{count:04d}"


def _log_audit(
    conn,
    reservation_id: str,
    action: str,
    performed_by: str,
    reason: str | None = None,
    previous_status: str | None = None,
    new_status: str | None = None,
    previous_dates: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO reservation_audit (
            id, reservation_id, action, performed_by,
            reason, previous_status, new_status, previous_dates, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            reservation_id,
            action,
            performed_by,
            reason,
            previous_status,
            new_status,
            previous_dates,
            _now(),
        ),
    )


def _get_res_row(conn, reservation_id: str):
    return conn.execute(
        "SELECT * FROM reservations WHERE id = ?", (reservation_id,)
    ).fetchone()


def create_reservation(
    employee_email: str,
    room_id: str,
    checkin: str,
    checkout: str,
    purpose: str,
) -> dict:
    init_audit_db()
    room = get_room(room_id)
    if not room:
        raise ValueError(f"Room {room_id} not found")
    if purpose not in VISIT_PURPOSES:
        raise ValueError(f"Invalid purpose. Choose from: {VISIT_PURPOSES}")

    checkin_d = date.fromisoformat(checkin)
    checkout_d = date.fromisoformat(checkout)
    if checkin_d <= date.today():
        raise ValueError("Check-in date must be in the future")
    if checkout_d <= checkin_d:
        raise ValueError("Check-out must be after check-in")

    availability = get_availability(checkin, checkout, room["guesthouse_id"])
    room_avail = next((r for r in availability if r["room_id"] == room_id), None)
    if not room_avail or not room_avail["available"]:
        raise ValueError(
            "Room is not available for the requested dates. "
            f"Unavailable dates: {room_avail.get('unavailable_dates', []) if room_avail else 'unknown'}"
        )

    settings = get_settings()
    auto_hours = int(settings.reservation_auto_approve_hours or 24)
    now = _now()
    reservation_id = str(uuid.uuid4())
    auto_approve_at = (datetime.now(timezone.utc) + timedelta(hours=auto_hours)).isoformat()

    with _lock:
        with connect() as conn:
            conf_number = _generate_confirmation_number(conn)
            conn.execute(
                """
                INSERT INTO reservations (
                    id, confirmation_number, employee_email, room_id, guesthouse_id,
                    checkin_date, checkout_date, purpose, status,
                    created_at, auto_approve_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reservation_id,
                    conf_number,
                    _email(employee_email),
                    room_id,
                    room["guesthouse_id"],
                    checkin,
                    checkout,
                    purpose,
                    STATUS_PENDING,
                    now,
                    auto_approve_at,
                ),
            )
            mark_dates_booked(room_id, checkin, checkout, reservation_id, conn)
            _log_audit(
                conn,
                reservation_id,
                "created",
                _email(employee_email),
                new_status=STATUS_PENDING,
            )
            conn.commit()

    logger.info(
        "Reservation created %s — %s → %s Room %s (%s to %s)",
        conf_number,
        employee_email,
        room["guesthouse_name"],
        room["room_number"],
        checkin,
        checkout,
    )
    return get_reservation(reservation_id)


def get_reservation(reservation_id: str) -> Optional[dict]:
    init_audit_db()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT r.*,
                   rm.room_number, rm.room_name, rm.capacity,
                   g.name as guesthouse_name, g.address as guesthouse_address
            FROM reservations r
            JOIN rooms rm ON rm.id = r.room_id
            JOIN guesthouses g ON g.id = r.guesthouse_id
            WHERE r.id = ?
            """,
            (reservation_id,),
        ).fetchone()
        return _row(row) if row else None


def get_reservation_by_confirmation(conf_number: str) -> Optional[dict]:
    init_audit_db()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT r.*,
                   rm.room_number, rm.room_name, rm.capacity,
                   g.name as guesthouse_name, g.address as guesthouse_address
            FROM reservations r
            JOIN rooms rm ON rm.id = r.room_id
            JOIN guesthouses g ON g.id = r.guesthouse_id
            WHERE r.confirmation_number = ?
            """,
            (conf_number.strip().upper(),),
        ).fetchone()
        return _row(row) if row else None


def get_my_reservations(employee_email: str) -> List[dict]:
    init_audit_db()
    email = _email(employee_email)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT r.*,
                   rm.room_number, rm.room_name,
                   g.name as guesthouse_name, g.address as guesthouse_address
            FROM reservations r
            JOIN rooms rm ON rm.id = r.room_id
            JOIN guesthouses g ON g.id = r.guesthouse_id
            WHERE r.employee_email = ?
            ORDER BY r.checkin_date DESC
            """,
            (email,),
        ).fetchall()
        return [_row(r) for r in rows]


def get_upcoming_reservations(employee_email: str) -> List[dict]:
    init_audit_db()
    today = date.today().isoformat()
    email = _email(employee_email)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT r.*,
                   rm.room_number, rm.room_name,
                   g.name as guesthouse_name, g.address as guesthouse_address
            FROM reservations r
            JOIN rooms rm ON rm.id = r.room_id
            JOIN guesthouses g ON g.id = r.guesthouse_id
            WHERE r.employee_email = ?
              AND r.checkout_date >= ?
              AND r.status IN ('pending_approval', 'confirmed')
            ORDER BY r.checkin_date ASC
            """,
            (email, today),
        ).fetchall()
        return [_row(r) for r in rows]


def get_all_reservations(
    status: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    guesthouse_id: Optional[str] = None,
) -> List[dict]:
    init_audit_db()
    query = """
        SELECT r.*,
               rm.room_number, rm.room_name,
               g.name as guesthouse_name, g.address as guesthouse_address
        FROM reservations r
        JOIN rooms rm ON rm.id = r.room_id
        JOIN guesthouses g ON g.id = r.guesthouse_id
        WHERE 1=1
    """
    params: list = []
    if status:
        query += " AND r.status = ?"
        params.append(status)
    if from_date:
        query += " AND r.checkin_date >= ?"
        params.append(from_date)
    if to_date:
        query += " AND r.checkout_date <= ?"
        params.append(to_date)
    if guesthouse_id:
        query += " AND r.guesthouse_id = ?"
        params.append(guesthouse_id)
    query += " ORDER BY r.checkin_date DESC"

    with connect() as conn:
        rows = conn.execute(query, params).fetchall()
        return [_row(r) for r in rows]


def get_pending_reservations() -> List[dict]:
    return get_all_reservations(status=STATUS_PENDING)


def approve_reservation(reservation_id: str, approved_by: str) -> dict:
    init_audit_db()
    now = _now()
    with _lock:
        with connect() as conn:
            res = _get_res_row(conn, reservation_id)
            if not res:
                raise ValueError("Reservation not found")
            if res["status"] != STATUS_PENDING:
                raise ValueError(
                    f"Can only approve pending reservations. Current status: {res['status']}"
                )
            conn.execute(
                """
                UPDATE reservations
                SET status = 'confirmed', approved_at = ?, approved_by = ?
                WHERE id = ?
                """,
                (now, _email(approved_by), reservation_id),
            )
            _log_audit(
                conn,
                reservation_id,
                "approved",
                _email(approved_by),
                previous_status=STATUS_PENDING,
                new_status=STATUS_CONFIRMED,
            )
            conn.commit()
    return get_reservation(reservation_id)


def reject_reservation(
    reservation_id: str,
    rejected_by: str,
    reason: str,
) -> dict:
    init_audit_db()
    now = _now()
    with _lock:
        with connect() as conn:
            res = _get_res_row(conn, reservation_id)
            if not res:
                raise ValueError("Reservation not found")
            if res["status"] != STATUS_PENDING:
                raise ValueError("Can only reject pending reservations")
            conn.execute(
                """
                UPDATE reservations
                SET status = 'rejected', rejected_at = ?, rejected_by = ?,
                    rejection_reason = ?
                WHERE id = ?
                """,
                (now, _email(rejected_by), reason, reservation_id),
            )
            mark_dates_available(
                res["room_id"], res["checkin_date"], res["checkout_date"], conn
            )
            _log_audit(
                conn,
                reservation_id,
                "rejected",
                _email(rejected_by),
                reason=reason,
                previous_status=STATUS_PENDING,
                new_status=STATUS_REJECTED,
            )
            conn.commit()
    return get_reservation(reservation_id)


def cancel_reservation(reservation_id: str, cancelled_by: str) -> dict:
    init_audit_db()
    now = _now()
    with _lock:
        with connect() as conn:
            res = _get_res_row(conn, reservation_id)
            if not res:
                raise ValueError("Reservation not found")
            res_dict = dict(res)
            ok, msg = can_modify(res_dict)
            if not ok:
                raise ValueError(msg)
            conn.execute(
                """
                UPDATE reservations
                SET status = 'cancelled', cancelled_at = ?, cancelled_by = ?
                WHERE id = ?
                """,
                (now, _email(cancelled_by), reservation_id),
            )
            mark_dates_available(
                res["room_id"], res["checkin_date"], res["checkout_date"], conn
            )
            _log_audit(
                conn,
                reservation_id,
                "cancelled",
                _email(cancelled_by),
                previous_status=res["status"],
                new_status=STATUS_CANCELLED,
            )
            conn.commit()
    return get_reservation(reservation_id)


def override_reservation(
    reservation_id: str,
    override_by: str,
    reason: str,
) -> dict:
    init_audit_db()
    now = _now()
    with _lock:
        with connect() as conn:
            res = _get_res_row(conn, reservation_id)
            if not res:
                raise ValueError("Reservation not found")
            if res["status"] in (STATUS_OVERRIDDEN, STATUS_COMPLETED, STATUS_EXPIRED):
                raise ValueError(f"Cannot override reservation with status: {res['status']}")
            conn.execute(
                """
                UPDATE reservations
                SET status = 'overridden', override_at = ?,
                    override_by = ?, override_reason = ?
                WHERE id = ?
                """,
                (now, _email(override_by), reason, reservation_id),
            )
            mark_dates_available(
                res["room_id"], res["checkin_date"], res["checkout_date"], conn
            )
            _log_audit(
                conn,
                reservation_id,
                "overridden",
                _email(override_by),
                reason=reason,
                previous_status=res["status"],
                new_status=STATUS_OVERRIDDEN,
            )
            conn.commit()
    return get_reservation(reservation_id)


def modify_reservation(
    reservation_id: str,
    modified_by: str,
    new_checkin: str,
    new_checkout: str,
) -> dict:
    init_audit_db()
    now = _now()
    settings = get_settings()
    auto_hours = int(settings.reservation_auto_approve_hours or 24)

    with _lock:
        with connect() as conn:
            res = _get_res_row(conn, reservation_id)
            if not res:
                raise ValueError("Reservation not found")
            res_dict = dict(res)
            if res_dict["status"] != STATUS_CONFIRMED:
                raise ValueError("Can only modify confirmed reservations")
            ok, msg = can_modify(res_dict)
            if not ok:
                raise ValueError(msg)

            new_avail = get_availability(
                new_checkin, new_checkout, exclude_reservation_id=reservation_id
            )
            room_avail = next(
                (r for r in new_avail if r["room_id"] == res["room_id"]), None
            )
            if not room_avail or not room_avail["available"]:
                raise ValueError(
                    "The new dates are not available for this room. "
                    "Please choose different dates."
                )

            old_checkin = res["checkin_date"]
            old_checkout = res["checkout_date"]
            mark_dates_available(res["room_id"], old_checkin, old_checkout, conn)
            mark_dates_booked(res["room_id"], new_checkin, new_checkout, reservation_id, conn)

            auto_approve_at = (
                datetime.now(timezone.utc) + timedelta(hours=auto_hours)
            ).isoformat()
            conn.execute(
                """
                UPDATE reservations
                SET checkin_date = ?, checkout_date = ?,
                    status = 'pending_approval',
                    last_modified_at = ?,
                    modification_count = modification_count + 1,
                    approved_at = NULL, approved_by = NULL,
                    auto_approve_at = ?
                WHERE id = ?
                """,
                (
                    new_checkin,
                    new_checkout,
                    now,
                    auto_approve_at,
                    reservation_id,
                ),
            )
            _log_audit(
                conn,
                reservation_id,
                "modified",
                _email(modified_by),
                previous_status=STATUS_CONFIRMED,
                new_status=STATUS_PENDING,
                previous_dates=json.dumps(
                    {"checkin": old_checkin, "checkout": old_checkout}
                ),
            )
            conn.commit()

    return get_reservation(reservation_id)


def admin_create_reservation(
    employee_email: str,
    room_id: str,
    checkin: str,
    checkout: str,
    purpose: str,
    created_by: str,
    *,
    auto_confirm: bool = True,
) -> dict:
    """HR creates a reservation on behalf of an employee."""
    init_audit_db()
    room = get_room(room_id)
    if not room:
        raise ValueError(f"Room {room_id} not found")
    if purpose not in VISIT_PURPOSES:
        raise ValueError(f"Invalid purpose. Choose from: {VISIT_PURPOSES}")

    checkin_d = date.fromisoformat(checkin)
    checkout_d = date.fromisoformat(checkout)
    if checkin_d < date.today():
        raise ValueError("Check-in date cannot be in the past")
    if checkout_d <= checkin_d:
        raise ValueError("Check-out must be after check-in")

    availability = get_availability(checkin, checkout, room["guesthouse_id"])
    room_avail = next((r for r in availability if r["room_id"] == room_id), None)
    if not room_avail or not room_avail["available"]:
        raise ValueError(
            "Room is not available for the requested dates. "
            f"Unavailable dates: {room_avail.get('unavailable_dates', []) if room_avail else 'unknown'}"
        )

    settings = get_settings()
    auto_hours = int(settings.reservation_auto_approve_hours or 24)
    now = _now()
    reservation_id = str(uuid.uuid4())
    auto_approve_at = (datetime.now(timezone.utc) + timedelta(hours=auto_hours)).isoformat()
    status = STATUS_CONFIRMED if auto_confirm else STATUS_PENDING
    approved_at = now if auto_confirm else None
    approved_by = _email(created_by) if auto_confirm else None

    with _lock:
        with connect() as conn:
            conf_number = _generate_confirmation_number(conn)
            conn.execute(
                """
                INSERT INTO reservations (
                    id, confirmation_number, employee_email, room_id, guesthouse_id,
                    checkin_date, checkout_date, purpose, status,
                    created_at, auto_approve_at, approved_at, approved_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reservation_id,
                    conf_number,
                    _email(employee_email),
                    room_id,
                    room["guesthouse_id"],
                    checkin,
                    checkout,
                    purpose,
                    status,
                    now,
                    auto_approve_at,
                    approved_at,
                    approved_by,
                ),
            )
            mark_dates_booked(room_id, checkin, checkout, reservation_id, conn)
            _log_audit(
                conn,
                reservation_id,
                "admin_created",
                _email(created_by),
                new_status=status,
            )
            conn.commit()

    return get_reservation(reservation_id)


def admin_modify_reservation(
    reservation_id: str,
    modified_by: str,
    new_checkin: str,
    new_checkout: str,
) -> dict:
    """HR modifies dates without employee ownership or 48h cutoff."""
    init_audit_db()
    now = _now()

    with _lock:
        with connect() as conn:
            res = _get_res_row(conn, reservation_id)
            if not res:
                raise ValueError("Reservation not found")
            res_dict = dict(res)
            status = (res_dict.get("status") or "").lower()
            if status not in (STATUS_PENDING, STATUS_CONFIRMED):
                raise ValueError(f"Cannot modify reservation with status: {status}")

            new_avail = get_availability(
                new_checkin, new_checkout, exclude_reservation_id=reservation_id
            )
            room_avail = next(
                (r for r in new_avail if r["room_id"] == res["room_id"]), None
            )
            if not room_avail or not room_avail["available"]:
                raise ValueError(
                    "The new dates are not available for this room. "
                    "Please choose different dates."
                )

            old_checkin = res["checkin_date"]
            old_checkout = res["checkout_date"]
            mark_dates_available(res["room_id"], old_checkin, old_checkout, conn)
            mark_dates_booked(
                res["room_id"], new_checkin, new_checkout, reservation_id, conn
            )

            conn.execute(
                """
                UPDATE reservations
                SET checkin_date = ?, checkout_date = ?,
                    last_modified_at = ?,
                    modification_count = modification_count + 1
                WHERE id = ?
                """,
                (new_checkin, new_checkout, now, reservation_id),
            )
            _log_audit(
                conn,
                reservation_id,
                "admin_modified",
                _email(modified_by),
                previous_status=status,
                new_status=status,
                previous_dates=json.dumps(
                    {"checkin": old_checkin, "checkout": old_checkout}
                ),
            )
            conn.commit()

    return get_reservation(reservation_id)


def admin_cancel_reservation(reservation_id: str, cancelled_by: str) -> dict:
    """HR cancels any pending or confirmed reservation."""
    init_audit_db()
    now = _now()
    with _lock:
        with connect() as conn:
            res = _get_res_row(conn, reservation_id)
            if not res:
                raise ValueError("Reservation not found")
            status = (res["status"] or "").lower()
            if status in (STATUS_CANCELLED, STATUS_REJECTED, STATUS_OVERRIDDEN, STATUS_COMPLETED, STATUS_EXPIRED):
                raise ValueError(f"Cannot cancel reservation with status: {status}")
            conn.execute(
                """
                UPDATE reservations
                SET status = 'cancelled', cancelled_at = ?, cancelled_by = ?
                WHERE id = ?
                """,
                (now, _email(cancelled_by), reservation_id),
            )
            mark_dates_available(
                res["room_id"], res["checkin_date"], res["checkout_date"], conn
            )
            _log_audit(
                conn,
                reservation_id,
                "admin_cancelled",
                _email(cancelled_by),
                previous_status=res["status"],
                new_status=STATUS_CANCELLED,
            )
            conn.commit()
    return get_reservation(reservation_id)


def mark_notified(reservation_id: str, notification_type: str) -> None:
    col_map = {
        "48h": "notified_48h",
        "checkin": "notified_checkin",
        "checkout": "notified_checkout",
    }
    col = col_map.get(notification_type)
    if not col:
        raise ValueError(f"Unknown notification type: {notification_type}")
    with connect() as conn:
        conn.execute(f"UPDATE reservations SET {col} = 1 WHERE id = ?", (reservation_id,))
        conn.commit()


def get_reservations_due_auto_approve() -> List[dict]:
    init_audit_db()
    now = _now()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT r.*,
                   rm.room_number, rm.room_name,
                   g.name as guesthouse_name, g.address as guesthouse_address
            FROM reservations r
            JOIN rooms rm ON rm.id = r.room_id
            JOIN guesthouses g ON g.id = r.guesthouse_id
            WHERE r.status = 'pending_approval' AND r.auto_approve_at <= ?
            """,
            (now,),
        ).fetchall()
        return [_row(r) for r in rows]


def get_reservations_needing_reminders() -> dict:
    init_audit_db()
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    with connect() as conn:
        remind_48h = conn.execute(
            """
            SELECT r.*, rm.room_number, rm.room_name,
                   g.name as guesthouse_name, g.address as guesthouse_address
            FROM reservations r
            JOIN rooms rm ON rm.id = r.room_id
            JOIN guesthouses g ON g.id = r.guesthouse_id
            WHERE r.status = 'confirmed' AND r.checkin_date = ? AND r.notified_48h = 0
            """,
            (tomorrow,),
        ).fetchall()
        remind_checkin = conn.execute(
            """
            SELECT r.*, rm.room_number, rm.room_name,
                   g.name as guesthouse_name, g.address as guesthouse_address
            FROM reservations r
            JOIN rooms rm ON rm.id = r.room_id
            JOIN guesthouses g ON g.id = r.guesthouse_id
            WHERE r.status = 'confirmed' AND r.checkin_date = ? AND r.notified_checkin = 0
            """,
            (today,),
        ).fetchall()
        remind_checkout = conn.execute(
            """
            SELECT r.*, rm.room_number, rm.room_name,
                   g.name as guesthouse_name, g.address as guesthouse_address
            FROM reservations r
            JOIN rooms rm ON rm.id = r.room_id
            JOIN guesthouses g ON g.id = r.guesthouse_id
            WHERE r.status = 'confirmed' AND r.checkout_date = ? AND r.notified_checkout = 0
            """,
            (today,),
        ).fetchall()
        return {
            "remind_48h": [_row(r) for r in remind_48h],
            "remind_checkin": [_row(r) for r in remind_checkin],
            "remind_checkout": [_row(r) for r in remind_checkout],
        }


def mark_completed_reservations() -> int:
    init_audit_db()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    with connect() as conn:
        cur = conn.execute(
            """
            UPDATE reservations SET status = 'completed'
            WHERE status = 'confirmed' AND checkout_date <= ?
            """,
            (yesterday,),
        )
        conn.commit()
        return cur.rowcount


def get_audit_log(reservation_id: str) -> List[dict]:
    init_audit_db()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM reservation_audit
            WHERE reservation_id = ? ORDER BY timestamp ASC
            """,
            (reservation_id,),
        ).fetchall()
        return [_row(r) for r in rows]


def get_occupancy_report(from_date: str, to_date: str) -> dict:
    init_audit_db()
    with connect() as conn:
        total_room_days = conn.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT DISTINCT room_id, date FROM availability
                WHERE date >= ? AND date <= ?
            )
            """,
            (from_date, to_date),
        ).fetchone()[0]
        booked_days = conn.execute(
            """
            SELECT COUNT(*) FROM availability
            WHERE date >= ? AND date <= ? AND status = 'booked'
            """,
            (from_date, to_date),
        ).fetchone()[0]
        total_reservations = conn.execute(
            """
            SELECT COUNT(*) FROM reservations
            WHERE checkin_date >= ? AND checkout_date <= ?
              AND status NOT IN ('rejected', 'expired')
            """,
            (from_date, to_date),
        ).fetchone()[0]
        occupancy_pct = (
            round(booked_days / total_room_days * 100, 1) if total_room_days > 0 else 0
        )
        return {
            "from_date": from_date,
            "to_date": to_date,
            "total_room_days": total_room_days,
            "booked_days": booked_days,
            "occupancy_pct": occupancy_pct,
            "total_reservations": total_reservations,
        }
