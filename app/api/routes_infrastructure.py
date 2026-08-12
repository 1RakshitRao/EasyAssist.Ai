"""Office infrastructure admin API — printer registry."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException

from app.auth.deps import AdminUser
from app.infrastructure import store
from app.models.schemas import CreateOfficePrinterRequest, OfficePrinterOut

router = APIRouter(tags=["infrastructure"])


def _printer_out(data: dict) -> OfficePrinterOut:
    return OfficePrinterOut(
        id=data["id"],
        office_location=data["office_location"],
        printer_name=data["printer_name"],
        printer_ip=data["printer_ip"],
        ipp_port=int(data.get("ipp_port") or 631),
        ipp_path=data.get("ipp_path") or "/ipp/print",
        model=data.get("model"),
        floor=data.get("floor"),
        notes=data.get("notes"),
        active=bool(data.get("active", 1)),
        created_at=data.get("created_at") or "",
    )


@router.get("/admin/office-printers", response_model=List[OfficePrinterOut])
def list_office_printers(_admin: AdminUser):
    return [_printer_out(p) for p in store.list_printers(active_only=False)]


@router.post("/admin/office-printers", response_model=OfficePrinterOut, status_code=201)
def create_office_printer(req: CreateOfficePrinterRequest, _admin: AdminUser):
    data = store.create_printer(
        office_location=req.office_location,
        printer_name=req.printer_name,
        printer_ip=req.printer_ip,
        ipp_port=req.ipp_port,
        ipp_path=req.ipp_path,
        model=req.model,
        floor=req.floor,
        notes=req.notes,
    )
    return _printer_out(data)


@router.delete("/admin/office-printers/{printer_id}", status_code=204)
def delete_office_printer(printer_id: str, _admin: AdminUser):
    if not store.delete_printer(printer_id):
        raise HTTPException(status_code=404, detail="Printer not found")
