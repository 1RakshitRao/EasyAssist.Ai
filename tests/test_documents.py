"""Document assistant — extract, store, options, analyze, push."""

from __future__ import annotations

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


def test_session_store_expiry(doc_db, monkeypatch):
    monkeypatch.setenv("DOCUMENT_TTL_SECONDS", "1")
    get_settings.cache_clear()
    upsert_document(
        session_id="sess_exp",
        user_email="emp@ampcus.com",
        filename="old.txt",
        text="expires soon",
    )
    # Force expiry by rewriting expires_at
    from app.audit.db import connect

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with connect() as conn:
        conn.execute(
            "UPDATE chat_documents SET expires_at = ? WHERE session_id = ?",
            (past, "sess_exp"),
        )
        conn.commit()
    assert get_active_document("sess_exp", "emp@ampcus.com") is None


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
