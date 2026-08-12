"""Tests for Direct IPP printing."""

from __future__ import annotations

from unittest.mock import patch

from app.infrastructure.ipp_client import IppPrintResult, send_print_job, _looks_like_network_error
from app.infrastructure.print import handle_print_document
from app.infrastructure import store


def test_looks_like_network_error_distinguishes_ipp_http():
    assert _looks_like_network_error(["HTTP 500 from printer at 10.1.0.22:50081/"]) is False
    assert _looks_like_network_error(["Connection refused"]) is True


def test_send_print_job_simulates_on_network_error_only():
    with patch("app.infrastructure.ipp_client._send_via_ippx") as mock_send:
        mock_send.return_value = IppPrintResult(
            success=False,
            error_message="Connection refused",
        )
        with patch("app.infrastructure.ipp_client.get_settings") as mock_settings:
            mock_settings.return_value.print_enabled = True
            mock_settings.return_value.print_simulate_when_unreachable = True
            mock_settings.return_value.print_ipp_timeout_seconds = 30.0
            result = send_print_job(
                printer_ip="10.1.0.22",
                file_bytes=b"%PDF-1.4 test",
                filename="test.pdf",
                content_type="application/pdf",
                ipp_port=50081,
            )
    assert result.success
    assert result.simulated


def test_send_print_job_surfaces_ipp_http_error():
    with patch("app.infrastructure.ipp_client._send_via_ippx") as mock_send:
        mock_send.return_value = IppPrintResult(
            success=False,
            error_message="HTTP 500 from printer at 10.1.0.22:50081/ipp/print",
        )
        with patch("app.infrastructure.ipp_client.get_settings") as mock_settings:
            mock_settings.return_value.print_enabled = True
            mock_settings.return_value.print_simulate_when_unreachable = True
            mock_settings.return_value.print_ipp_timeout_seconds = 30.0
            result = send_print_job(
                printer_ip="10.1.0.22",
                file_bytes=b"%PDF-1.4",
                filename="doc.pdf",
                content_type="application/pdf",
                ipp_port=50081,
            )
    assert not result.success
    assert not result.simulated
    assert "HTTP 500" in (result.error_message or "")
    assert "10.1.0.22:50081" in (result.error_message or "")


def test_send_print_job_success_via_ippx():
    with patch("app.infrastructure.ipp_client._send_via_ippx") as mock_send:
        mock_send.return_value = IppPrintResult(
            success=True,
            job_id="42",
            ipp_path="/ipp/print",
        )
        with patch("app.infrastructure.ipp_client.get_settings") as mock_settings:
            mock_settings.return_value.print_enabled = True
            mock_settings.return_value.print_simulate_when_unreachable = False
            mock_settings.return_value.print_ipp_timeout_seconds = 30.0
            result = send_print_job(
                printer_ip="10.1.0.22",
                file_bytes=b"%PDF-1.4",
                filename="doc.pdf",
                content_type="application/pdf",
                ipp_port=50081,
            )
    assert result.success
    assert result.job_id == "42"
    assert not result.simulated


def test_print_rejects_docx():
    store.seed_office_printers_if_empty()
    with patch("app.infrastructure.print.get_active_document") as mock_doc:
        mock_doc.return_value = {
            "filename": "report.docx",
            "stored_path": "sess/id_report.docx",
        }
        result = handle_print_document(
            user_email="employee@ampcus.com",
            session_id="sess",
        )
    assert "PDF" in result["answer"]


def test_print_no_printer_configured():
    with patch("app.infrastructure.print.store.get_default_printer", return_value=None):
        result = handle_print_document(
            user_email="employee@ampcus.com",
            session_id="sess",
        )
    assert "no office printer" in result["answer"].lower()


def test_print_surfaces_ipp_failure_in_chat(tmp_path):
    store.seed_office_printers_if_empty()
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 content")

    with patch("app.infrastructure.print.get_active_document") as mock_doc:
        with patch("app.infrastructure.print.send_print_job") as mock_print:
            mock_doc.return_value = {
                "filename": "test.pdf",
                "stored_path": "sess/test.pdf",
            }
            with patch("app.infrastructure.print.absolute_path", return_value=pdf_path):
                mock_print.return_value = IppPrintResult(
                    success=False,
                    error_message="Could not print to 10.1.0.22:50081. Printer reported: HTTP 500",
                )
                result = handle_print_document(
                    user_email="employee@ampcus.com",
                    session_id="sess",
                )

    assert "HTTP 500" in result["answer"]


def test_print_sends_to_default_printer(tmp_path):
    store.seed_office_printers_if_empty()
    pdf_path = tmp_path / "doc1_test.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 content")

    with patch("app.infrastructure.print.get_active_document") as mock_doc:
        with patch("app.infrastructure.print.send_print_job") as mock_print:
            mock_doc.return_value = {
                "filename": "test.pdf",
                "stored_path": "sess/doc1_test.pdf",
            }
            with patch("app.infrastructure.print.absolute_path", return_value=pdf_path):
                mock_print.return_value = IppPrintResult(success=True, job_id="1")
                result = handle_print_document(
                    user_email="employee@ampcus.com",
                    session_id="sess",
                )

    assert "Printing now" in result["answer"]
    mock_print.assert_called_once()
    call_kw = mock_print.call_args.kwargs
    assert call_kw["printer_ip"] == "10.1.0.22"
    assert call_kw["ipp_port"] == 50081
    assert call_kw["content_type"] == "application/pdf"
