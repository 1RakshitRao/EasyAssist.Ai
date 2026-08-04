"""Document assistant — extract, store, options, analyze, push."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest

from app.config import get_settings
from app.documents.analysis_agent import AnalysisResult, analyze_document
from app.documents.chunker import chunk_text
from app.documents.cleaner import clean_text
from app.documents.extractor import (
    EmptyDocumentError,
    UnsupportedDocumentType,
    extract_text,
    extract_txt,
)
from app.documents.kb_pusher import PushResult, push_to_kb, suggest_department
from app.documents.options import get_options, is_allowed_operation
from app.documents.session_store import get_active_document, upsert_document


@pytest.fixture()
def doc_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    get_settings.cache_clear()
    from app.audit.db import init_audit_db

    init_audit_db()
    yield
    get_settings.cache_clear()


def test_extract_txt_and_reject_bad_type():
    assert "hello" in extract_txt(b"hello world").lower()
    with pytest.raises(UnsupportedDocumentType):
        extract_text(b"x", "scan.png")
    with pytest.raises(EmptyDocumentError):
        extract_text(b"", "a.txt")


def test_extract_docx_roundtrip():
    from docx import Document

    buf = BytesIO()
    doc = Document()
    doc.add_paragraph("Ampcus leave policy requires 20 days notice.")
    doc.save(buf)
    text = extract_text(buf.getvalue(), "policy.docx")
    assert "leave policy" in text.lower()


def test_clean_text_strips_page_noise():
    raw = "Hello\n\n\nPage 3 of 10\nWorld   team\n- 4 -\n"
    cleaned = clean_text(raw)
    assert "Page 3" not in cleaned
    assert "Hello" in cleaned
    assert "World team" in cleaned


def test_session_store_one_doc_and_replace(doc_db):
    meta1 = upsert_document(
        session_id="sess_a",
        user_email="emp@ampcus.com",
        filename="a.txt",
        text="first document body",
    )
    meta2 = upsert_document(
        session_id="sess_a",
        user_email="emp@ampcus.com",
        filename="b.txt",
        text="second document body",
    )
    assert meta1["doc_id"] != meta2["doc_id"]
    active = get_active_document("sess_a", "emp@ampcus.com")
    assert active is not None
    assert active["filename"] == "b.txt"
    assert "second" in active["text"]


def test_session_store_text_ttl_keeps_meta(doc_db, monkeypatch):
    monkeypatch.setenv("DOCUMENT_TTL_SECONDS", "1")
    get_settings.cache_clear()
    meta = upsert_document(
        session_id="sess_exp",
        user_email="emp@ampcus.com",
        filename="old.txt",
        text="expires soon",
        stored_path="sess_exp/x_old.txt",
        preview_kind_value="text",
    )
    from app.audit.db import connect
    from app.documents.session_store import get_document_for_preview

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    with connect() as conn:
        conn.execute(
            """
            UPDATE chat_documents
            SET expires_at = ?, text_expires_at = ?, file_expires_at = ?
            WHERE session_id = ?
            """,
            (past, past, future, "sess_exp"),
        )
        conn.commit()
    active = get_active_document("sess_exp", "emp@ampcus.com", include_text=True)
    assert active is not None
    assert active.get("text") is None
    assert active.get("text_expired") is True
    preview = get_document_for_preview("sess_exp", meta["doc_id"], "emp@ampcus.com")
    assert preview is not None
    assert preview["stored_path"] == "sess_exp/x_old.txt"


def test_session_store_file_ttl_removes_row(doc_db):
    meta = upsert_document(
        session_id="sess_file_exp",
        user_email="emp@ampcus.com",
        filename="gone.txt",
        text="file ttl gone",
    )
    from app.audit.db import connect

    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with connect() as conn:
        conn.execute(
            """
            UPDATE chat_documents
            SET expires_at = ?, text_expires_at = ?, file_expires_at = ?
            WHERE session_id = ?
            """,
            (past, past, past, "sess_file_exp"),
        )
        conn.commit()
    assert get_active_document("sess_file_exp", "emp@ampcus.com") is None
    from app.documents.session_store import get_document_for_preview

    assert get_document_for_preview("sess_file_exp", meta["doc_id"], "emp@ampcus.com") is None


def test_options_by_role():
    emp = {o["id"] for o in get_options("employee")}
    adm = {o["id"] for o in get_options("admin")}
    assert "summarize" in emp
    assert "push_to_kb" not in emp
    assert "push_to_kb" in adm
    assert is_allowed_operation("employee", "summarize")
    assert not is_allowed_operation("employee", "push_to_kb")
    assert is_allowed_operation("admin", "push_to_kb")


def test_chunk_text_produces_chunks():
    text = " ".join(["Sentence number %d is here." % i for i in range(80)])
    chunks = chunk_text(text, source_name="x.txt")
    assert len(chunks) >= 1
    assert all(isinstance(c, str) and c.strip() for c in chunks)


def test_analyze_document_mocked(monkeypatch):
    class Fake:
        text = "Summary: leave is 20 days."
        model = "fake-haiku"
        token_usage = {"input_tokens": 10, "output_tokens": 5}

    monkeypatch.setattr(
        "app.documents.analysis_agent.complete",
        lambda **_k: Fake(),
    )
    monkeypatch.setattr(
        "app.documents.analysis_agent.resolve_answer_model",
        lambda *_a, **_k: "fake-haiku",
    )
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    get_settings.cache_clear()
    out = analyze_document(
        text="Employees receive 20 days of leave per year.",
        operation="summarize",
        filename="leave.txt",
    )
    assert isinstance(out, AnalysisResult)
    assert "20 days" in out.result
    assert out.token_usage["input_tokens"] == 10


def test_suggest_department_heuristic():
    assert suggest_department("VPN laptop password reset instructions", "it-guide.txt") == "it"
    assert suggest_department("NDA liability agreement terms", "nda.txt") == "legal"


def test_push_to_kb_mocked(monkeypatch):
    monkeypatch.setattr(
        "app.documents.kb_pusher.chunk_text",
        lambda text, source_name="": ["chunk one", "chunk two"],
    )

    class FakeStore:
        def add_documents(self, dept, docs, check_duplicates=True):
            assert dept == "hr"
            assert docs

    monkeypatch.setattr("app.documents.kb_pusher.get_store", lambda: FakeStore())
    monkeypatch.setattr("app.documents.kb_pusher.append_event", lambda *_a, **_k: None)
    result = push_to_kb(
        text="handbook content " * 20,
        filename="handbook.txt",
        department="hr",
        uploaded_by={"id": "1", "email": "admin@ampcus.com", "role": "admin"},
    )
    assert isinstance(result, PushResult)
    assert result.ok
    assert result.chunks_created == 2
    assert len(result.doc_ids) == 2


def test_analyze_ask_requires_question():
    with pytest.raises(ValueError, match="question"):
        analyze_document(text="body", operation="ask", question="")


def test_push_rejects_bad_department():
    result = push_to_kb(
        text="x",
        filename="a.txt",
        department="finance",
        uploaded_by={"email": "admin@ampcus.com", "role": "admin"},
    )
    assert not result.ok
    assert "department" in result.error.lower()


def test_safe_filename_and_save_replace(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCUMENT_STORAGE_DIR", str(tmp_path / "docs"))
    get_settings.cache_clear()
    from app.documents.storage import (
        absolute_path,
        cleanup_old_document_files,
        save_file,
        safe_filename,
    )

    assert safe_filename("../../etc/passwd.txt") == "passwd.txt"
    assert ".." not in safe_filename("weird name!!!.pdf")

    p1 = save_file("sess1", "doc-a", "a.txt", b"first")
    assert p1.is_file()
    assert p1.read_bytes() == b"first"
    p2 = save_file("sess1", "doc-b", "b.txt", b"second")
    assert p2.is_file()
    assert not p1.exists()  # prior session files removed on replace
    assert p2.read_bytes() == b"second"

    with pytest.raises(ValueError, match="escapes"):
        absolute_path("../outside.txt")


def test_cleanup_old_document_files_by_mtime(tmp_path, monkeypatch):
    monkeypatch.setenv("DOCUMENT_STORAGE_DIR", str(tmp_path / "docs"))
    get_settings.cache_clear()
    from app.documents.storage import cleanup_old_document_files, documents_root, save_file

    save_file("old_sess", "d1", "old.txt", b"old")
    save_file("new_sess", "d2", "new.txt", b"new")
    root = documents_root()
    old_dir = root / "old_sess"
    # age the old session dir beyond 7 days
    old_mtime = time.time() - (8 * 86400)
    os.utime(old_dir, (old_mtime, old_mtime))
    removed = cleanup_old_document_files(max_age_days=7)
    assert removed >= 1
    assert not old_dir.exists()
    assert (root / "new_sess").is_dir()


def test_preview_kind_and_mammoth_html():
    from app.documents.preview import docx_to_html, preview_kind

    assert preview_kind("a.pdf") == "pdf"
    assert preview_kind("a.docx") == "html"
    assert preview_kind("a.txt") == "text"

    from docx import Document

    buf = BytesIO()
    doc = Document()
    doc.add_paragraph("Ampcus preview fixture paragraph.")
    doc.save(buf)
    html = docx_to_html(buf.getvalue())
    assert "Ampcus preview fixture" in html
    assert "<html" in html.lower()


def test_preview_ownership_403(client, employee_headers, admin_headers, tmp_path, monkeypatch):
    monkeypatch.setenv("DOCUMENT_STORAGE_DIR", str(tmp_path / "docstore"))
    get_settings.cache_clear()

    # employee creates a chat session via ensure on upload
    up = client.post(
        "/documents/upload",
        headers=employee_headers,
        files={"file": ("note.txt", b"hello preview world", "text/plain")},
        data={"session_id": "preview-sess-1"},
    )
    assert up.status_code == 200, up.text
    body = up.json()
    doc_id = body["doc_id"]
    sid = body["session_id"]

    ok = client.get(
        f"/documents/preview?session_id={sid}&doc_id={doc_id}",
        headers=employee_headers,
    )
    assert ok.status_code == 200, ok.text
    assert b"hello preview world" in ok.content

    forbidden = client.get(
        f"/documents/preview?session_id={sid}&doc_id={doc_id}",
        headers=admin_headers,
    )
    assert forbidden.status_code == 403, forbidden.text
