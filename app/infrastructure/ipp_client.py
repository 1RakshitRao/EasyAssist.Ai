"""IPP (Internet Printing Protocol) client — ippx library with detailed errors."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_IPP_PATHS = ("/ipp/print", "/")


@dataclass
class IppPrintResult:
    success: bool
    job_id: Optional[str] = None
    error_message: Optional[str] = None
    simulated: bool = False
    ipp_path: Optional[str] = None
    ipp_status: Optional[str] = None


def _candidate_paths(ipp_path: str) -> Iterable[str]:
    primary = ipp_path if ipp_path.startswith("/") else f"/{ipp_path}"
    seen: set[str] = set()
    for path in (primary, *DEFAULT_IPP_PATHS):
        if path not in seen:
            seen.add(path)
            yield path


def _printer_url(printer_ip: str, ipp_port: int, path: str) -> str:
    return f"http://{printer_ip}:{ipp_port}{path}"


def _format_attempt_error(
    *,
    printer_ip: str,
    ipp_port: int,
    path: str,
    exc: Exception,
) -> str:
    from ippx.exceptions import IppHttpError, IppResponseError

    endpoint = f"{printer_ip}:{ipp_port}{path}"
    if isinstance(exc, IppResponseError):
        detail = exc.status_message or exc.status_name
        return (
            f"IPP error at {endpoint}: {exc.status_name} "
            f"(0x{exc.status_code:04X}) — {detail}"
        )
    if isinstance(exc, IppHttpError):
        return f"{exc} from printer at {endpoint}"
    return f"Printer at {endpoint}: {exc}"


def _send_via_ippx(
    *,
    printer_ip: str,
    ipp_port: int,
    path: str,
    file_bytes: bytes,
    content_type: str,
    job_name: str,
    timeout: float,
) -> IppPrintResult:
    from ippx import IppClient
    from ippx.exceptions import IppError

    url = _printer_url(printer_ip, ipp_port, path)
    try:
        with IppClient(
            url,
            timeout=timeout,
            requesting_user_name="helpdesk",
        ) as client:
            job = client.print_job(
                file_bytes,
                document_format=content_type,
                job_name=job_name,
            )
        logger.info(
            "IPP print job sent via ippx printer=%s:%s path=%s job_id=%s",
            printer_ip,
            ipp_port,
            path,
            job.job_id,
        )
        return IppPrintResult(
            success=True,
            job_id=str(job.job_id),
            ipp_path=path,
        )
    except IppError as exc:
        msg = _format_attempt_error(
            printer_ip=printer_ip,
            ipp_port=ipp_port,
            path=path,
            exc=exc,
        )
        ipp_status = getattr(exc, "status_name", None)
        logger.warning("ippx print failed %s", msg)
        return IppPrintResult(
            success=False,
            error_message=msg,
            ipp_path=path,
            ipp_status=ipp_status,
        )
    except Exception as exc:
        msg = _format_attempt_error(
            printer_ip=printer_ip,
            ipp_port=ipp_port,
            path=path,
            exc=exc,
        )
        logger.warning("ippx print unexpected error %s", msg)
        return IppPrintResult(success=False, error_message=msg, ipp_path=path)


def send_print_job(
    *,
    printer_ip: str,
    file_bytes: bytes,
    filename: str,
    content_type: str,
    ipp_port: int = 631,
    ipp_path: str = "/ipp/print",
    job_name: str = "Helpdesk Print Job",
    timeout_seconds: float | None = None,
) -> IppPrintResult:
    """Send document to printer via RFC 8011 Print-Job (ippx)."""
    settings = get_settings()
    if not settings.print_enabled:
        logger.info(
            "Print disabled — simulating job filename=%s printer=%s:%s",
            filename,
            printer_ip,
            ipp_port,
        )
        return IppPrintResult(success=True, job_id="simulated", simulated=True)

    timeout = timeout_seconds if timeout_seconds is not None else settings.print_ipp_timeout_seconds
    errors: list[str] = []

    for path in _candidate_paths(ipp_path):
        result = _send_via_ippx(
            printer_ip=printer_ip,
            ipp_port=ipp_port,
            path=path,
            file_bytes=file_bytes,
            content_type=content_type,
            job_name=job_name,
            timeout=timeout,
        )
        if result.success:
            return result
        if result.error_message:
            errors.append(result.error_message)

    combined = "; ".join(errors) if errors else "No IPP path succeeded"
    logger.warning(
        "IPP print failed printer=%s:%s filename=%s errors=%s",
        printer_ip,
        ipp_port,
        filename,
        combined,
    )

    if settings.print_simulate_when_unreachable and _looks_like_network_error(errors):
        logger.info(
            "Simulating print job (network unreachable) filename=%s printer=%s:%s",
            filename,
            printer_ip,
            ipp_port,
        )
        return IppPrintResult(success=True, job_id="simulated", simulated=True)

    return IppPrintResult(
        success=False,
        error_message=(
            f"Could not print to {printer_ip}:{ipp_port}. "
            f"Printer reported: {combined}"
        ),
    )


def _looks_like_network_error(errors: list[str]) -> bool:
    """Only simulate success for connectivity issues, not IPP/HTTP rejections."""
    if not errors:
        return True
    joined = " ".join(errors).lower()
    network_markers = (
        "connect",
        "timeout",
        "timed out",
        "unreachable",
        "refused",
        "network",
        "name or service not known",
        "no route",
    )
    ipp_markers = ("ipp error", "http 4", "http 5", "0x04", "0x05")
    if any(m in joined for m in ipp_markers):
        return False
    return any(m in joined for m in network_markers)
