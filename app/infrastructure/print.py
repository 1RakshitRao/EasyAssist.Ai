"""Direct IPP print handler — default office printer and job submission."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from app.documents.storage import absolute_path
from app.documents.session_store import get_active_document
from app.infrastructure import store
from app.infrastructure.ipp_client import send_print_job

logger = logging.getLogger(__name__)

_PRINTABLE = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
}

_DOCX_MSG = (
    "Direct IPP printing supports PDF and TXT files. "
    "Please re-upload your document as a PDF and try again."
)


def _content_type_for_filename(filename: str) -> Optional[str]:
    ext = Path(filename or "").suffix.lower()
    return _PRINTABLE.get(ext)


def handle_print_document(
    *,
    user_email: str,
    session_id: str | None,
) -> Dict[str, Any]:
    """Send uploaded document to the office default printer via IPP."""
    printer = store.get_default_printer()
    if not printer:
        return {
            "answer": "No office printer is configured. Contact IT to register the printer.",
            "model_used": "infrastructure_print",
        }

    sid = (session_id or "").strip()
    if not sid:
        return {
            "answer": "Please upload a document in chat first, then say 'print this'.",
            "model_used": "infrastructure_print",
        }

    doc = get_active_document(sid, user_email, include_text=False)
    if not doc or not doc.get("stored_path"):
        return {
            "answer": (
                "No uploaded document found for this session. "
                "Upload a PDF or TXT file, then ask me to print it."
            ),
            "model_used": "infrastructure_print",
        }

    filename = str(doc.get("filename") or "document")
    content_type = _content_type_for_filename(filename)
    if not content_type:
        return {"answer": _DOCX_MSG, "model_used": "infrastructure_print"}

    try:
        file_path = absolute_path(str(doc["stored_path"]))
        file_bytes = file_path.read_bytes()
    except Exception as exc:
        logger.warning("Print file read failed: %s", exc)
        return {
            "answer": "Could not read the uploaded file. Please upload again and retry.",
            "model_used": "infrastructure_print",
        }

    result = send_print_job(
        printer_ip=str(printer["printer_ip"]),
        file_bytes=file_bytes,
        filename=filename,
        content_type=content_type,
        ipp_port=int(printer.get("ipp_port") or 631),
        ipp_path=str(printer.get("ipp_path") or "/ipp/print"),
        job_name=f"Print from {user_email}",
    )

    if not result.success:
        return {
            "answer": result.error_message or "Print job failed.",
            "model_used": "infrastructure_print",
        }

    floor = printer.get("floor") or ""
    floor_txt = f" — {floor} floor" if floor else ""
    sim_note = " (simulated — print disabled or printer unreachable)" if result.simulated else ""
    return {
        "answer": (
            f"Printing now at {printer.get('printer_name')}{floor_txt}{sim_note}."
        ),
        "model_used": "infrastructure_print",
        "printer_id": printer.get("id"),
        "simulated": result.simulated,
    }
