"""Guesthouse reservation REST API — employee + admin."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.auth.deps import AdminUser, CurrentUser
from app.models.schemas import (
    AdminCreateReservationRequest,
    AvailabilityConflictResolve,
    AvailabilityUploadResult,
    CreateReservationRequest,
    GuesthouseOut,
    GuesthouseWithRoomsOut,
    ModifyReservationRequest,
    OccupancyReportOut,
    RejectReservationRequest,
    ReservationOut,
    RoomOut,
    OverrideReservationRequest,
)
from app.reservations import availability as avail_mod
from app.reservations.calendar import build_admin_calendar_payload, build_calendar_payload
from app.reservations import store
from app.reservations.notifications import (
    fire_approve_notification,
    fire_cancel_notification,
    fire_create_notifications,
    fire_override_notification,
    fire_reject_notification,
    notify_excel_conflicts,
)

router = APIRouter(tags=["reservations"])


def _reservation_out(data: dict) -> ReservationOut:
    return ReservationOut(
        id=data["id"],
        confirmation_number=data["confirmation_number"],
        employee_email=data["employee_email"],
        room_id=data["room_id"],
        guesthouse_id=data["guesthouse_id"],
        checkin_date=data["checkin_date"],
        checkout_date=data["checkout_date"],
        purpose=data.get("purpose") or "",
        status=data["status"],
        guesthouse_name=data.get("guesthouse_name"),
        guesthouse_address=data.get("guesthouse_address"),
        room_number=data.get("room_number"),
        room_name=data.get("room_name"),
        created_at=data.get("created_at"),
        approved_at=data.get("approved_at"),
        auto_approve_at=data.get("auto_approve_at"),
    )


def _guesthouse_out(data: dict) -> GuesthouseOut:
    import json

    amenities = data.get("amenities")
    if isinstance(amenities, str):
        try:
            amenities = json.loads(amenities)
        except json.JSONDecodeError:
            amenities = []
    return GuesthouseOut(
        id=data["id"],
        name=data["name"],
        address=data.get("address") or "",
        city=data.get("city") or "",
        amenities=list(amenities or []),
        room_count=int(data.get("room_count") or 0),
    )


def _room_out(data: dict) -> RoomOut:
    import json

    amenities = data.get("amenities")
    if isinstance(amenities, str):
        try:
            amenities = json.loads(amenities)
        except json.JSONDecodeError:
            amenities = []
    return RoomOut(
        id=data["id"],
        guesthouse_id=data["guesthouse_id"],
        room_number=str(data.get("room_number") or ""),
        room_name=data.get("room_name") or "",
        capacity=int(data.get("capacity") or 2),
        amenities=list(amenities or []),
        guesthouse_name=data.get("guesthouse_name"),
    )


# --- Employee ---


@router.get("/reservations/calendar")
def get_calendar_widget(
    user: CurrentUser,
    guesthouse_id: str = Query(...),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    _ = user
    try:
        return build_calendar_payload(
            guesthouse_id=guesthouse_id,
            from_date=from_date,
            to_date=to_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reservations/availability")
def get_availability_endpoint(
    user: CurrentUser,
    guesthouse_id: Optional[str] = Query(None),
    checkin: str = Query(..., description="YYYY-MM-DD"),
    checkout: str = Query(..., description="YYYY-MM-DD"),
):
    _ = user
    try:
        rows = store.get_availability(checkin, checkout, guesthouse_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"checkin": checkin, "checkout": checkout, "rooms": rows}


@router.post("/reservations", response_model=ReservationOut, status_code=201)
def create_reservation_endpoint(req: CreateReservationRequest, user: CurrentUser):
    try:
        res = store.create_reservation(
            user["email"],
            req.room_id,
            req.checkin_date,
            req.checkout_date,
            req.purpose,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fire_create_notifications(res)
    return _reservation_out(res)


@router.get("/reservations/my", response_model=List[ReservationOut])
def my_reservations(user: CurrentUser):
    rows = store.get_upcoming_reservations(user["email"])
    return [_reservation_out(r) for r in rows]


@router.put("/reservations/{reservation_id}", response_model=ReservationOut)
def modify_reservation_endpoint(
    reservation_id: str,
    req: ModifyReservationRequest,
    user: CurrentUser,
):
    res = store.get_reservation(reservation_id)
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")
    if res["employee_email"].lower() != user["email"].lower():
        raise HTTPException(status_code=403, detail="Not your reservation")
    try:
        updated = store.modify_reservation(
            reservation_id,
            user["email"],
            req.checkin_date,
            req.checkout_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fire_create_notifications(updated)
    return _reservation_out(updated)


@router.delete("/reservations/{reservation_id}", response_model=ReservationOut)
def cancel_reservation_endpoint(reservation_id: str, user: CurrentUser):
    res = store.get_reservation(reservation_id)
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")
    if res["employee_email"].lower() != user["email"].lower():
        raise HTTPException(status_code=403, detail="Not your reservation")
    try:
        cancelled = store.cancel_reservation(reservation_id, user["email"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fire_cancel_notification(cancelled)
    return _reservation_out(cancelled)


# --- Admin ---


@router.get("/admin/guesthouses", response_model=List[GuesthouseOut])
def admin_list_guesthouses(_admin: AdminUser):
    return [_guesthouse_out(g) for g in store.get_all_guesthouses()]


@router.get("/admin/guesthouses/{guesthouse_id}", response_model=GuesthouseWithRoomsOut)
def admin_guesthouse_detail(guesthouse_id: str, _admin: AdminUser):
    gh = store.get_guesthouse_with_rooms(guesthouse_id)
    if not gh:
        raise HTTPException(status_code=404, detail="Guesthouse not found")
    base = _guesthouse_out(gh)
    return GuesthouseWithRoomsOut(
        **base.model_dump(),
        rooms=[_room_out(r) for r in gh.get("rooms", [])],
    )


@router.get("/admin/reservations", response_model=List[ReservationOut])
def admin_list_reservations(
    _admin: AdminUser,
    status: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    guesthouse_id: Optional[str] = Query(None),
):
    rows = store.get_all_reservations(status, from_date, to_date, guesthouse_id)
    return [_reservation_out(r) for r in rows]


@router.get("/admin/reservations/pending", response_model=List[ReservationOut])
def admin_pending_reservations(_admin: AdminUser):
    return [_reservation_out(r) for r in store.get_pending_reservations()]


@router.get("/admin/reservations/calendar/widget")
def admin_calendar_widget(
    _admin: AdminUser,
    guesthouse_id: str = Query(...),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
):
    try:
        return build_admin_calendar_payload(
            guesthouse_id=guesthouse_id,
            from_date=from_date,
            to_date=to_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/admin/reservations", response_model=ReservationOut, status_code=201)
def admin_create_reservation_endpoint(req: AdminCreateReservationRequest, admin: AdminUser):
    try:
        res = store.admin_create_reservation(
            req.employee_email,
            req.room_id,
            req.checkin_date,
            req.checkout_date,
            req.purpose,
            admin["email"],
            auto_confirm=req.auto_confirm,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if req.auto_confirm:
        fire_approve_notification(res)
    else:
        fire_create_notifications(res)
    return _reservation_out(res)


@router.put("/admin/reservations/{reservation_id}", response_model=ReservationOut)
def admin_modify_reservation_endpoint(
    reservation_id: str,
    req: ModifyReservationRequest,
    admin: AdminUser,
):
    try:
        updated = store.admin_modify_reservation(
            reservation_id,
            admin["email"],
            req.checkin_date,
            req.checkout_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _reservation_out(updated)


@router.delete("/admin/reservations/{reservation_id}", response_model=ReservationOut)
def admin_cancel_reservation_endpoint(reservation_id: str, admin: AdminUser):
    try:
        cancelled = store.admin_cancel_reservation(reservation_id, admin["email"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fire_cancel_notification(cancelled)
    return _reservation_out(cancelled)


@router.post("/admin/reservations/{reservation_id}/approve", response_model=ReservationOut)
def admin_approve_reservation(reservation_id: str, admin: AdminUser):
    try:
        res = store.approve_reservation(reservation_id, admin["email"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fire_approve_notification(res)
    return _reservation_out(res)


@router.post("/admin/reservations/{reservation_id}/reject", response_model=ReservationOut)
def admin_reject_reservation(
    reservation_id: str,
    req: RejectReservationRequest,
    admin: AdminUser,
):
    try:
        res = store.reject_reservation(reservation_id, admin["email"], req.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fire_reject_notification(res, req.reason)
    return _reservation_out(res)


@router.post("/admin/reservations/{reservation_id}/override", response_model=ReservationOut)
def admin_override_reservation(
    reservation_id: str,
    req: OverrideReservationRequest,
    admin: AdminUser,
):
    try:
        res = store.override_reservation(reservation_id, admin["email"], req.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    fire_override_notification(res, req.reason)
    return _reservation_out(res)


@router.post("/admin/availability/upload", response_model=AvailabilityUploadResult)
async def admin_upload_availability(
    admin: AdminUser,
    file: UploadFile = File(...),
):
    data = await file.read()
    try:
        result = avail_mod.process_excel_upload(data, admin["email"])
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("conflicts"):
        notify_excel_conflicts(result["conflicts"])
    return AvailabilityUploadResult(**result)


@router.post("/admin/availability/resolve")
def admin_resolve_availability(
    body: List[AvailabilityConflictResolve],
    admin: AdminUser,
):
    resolutions = [item.model_dump() for item in body]
    return avail_mod.resolve_conflicts(resolutions, admin["email"])


@router.get("/admin/reservations/calendar")
def admin_reservations_calendar(
    _admin: AdminUser,
    from_date: str = Query(...),
    to_date: str = Query(...),
    guesthouse_id: Optional[str] = Query(None),
):
    rows = store.get_all_reservations(
        from_date=from_date,
        to_date=to_date,
        guesthouse_id=guesthouse_id,
    )
    return {"from_date": from_date, "to_date": to_date, "reservations": rows}


@router.get("/admin/reservations/report", response_model=OccupancyReportOut)
def admin_occupancy_report(
    _admin: AdminUser,
    from_date: str = Query(...),
    to_date: str = Query(...),
):
    report = store.get_occupancy_report(from_date, to_date)
    return OccupancyReportOut(**report)
