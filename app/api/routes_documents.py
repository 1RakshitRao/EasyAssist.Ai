"""Chat document upload / analyze / KB push / preview API."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response

from app.audit.cost import costs_for_query
from app.audit.store import append_event
from app.auth.deps import AdminUser, CurrentUser
from app.chat.store import ensure_session, save_message
from app.config import get_settings
from app.documents.analysis_agent import analyze_document
from app.documents.cleaner import clean_text
from app.documents.extractor import (
    EmptyDocumentError,
    UnsupportedDocumentType,
    count_pages,
    extract_text,
)
from app.documents.kb_pusher import push_to_kb, suggest_department
from app.documents.options import get_options, is_allowed_operation
from app.documents.preview import ensure_docx_preview_html, preview_kind
from app.documents.session_store import (
    clear_document,
    document_owner_email,
    get_active_document,
    get_document_for_preview,
    upsert_document,
)
from app.documents.storage import (
    absolute_path,
    cleanup_old_document_files,
    file_relative_path,
    save_file,
)
from app.models.schemas import (
    DocumentActiveResponse,
    DocumentAnalyzeRequest,
    DocumentAnalyzeResponse,
    DocumentOption,
    DocumentPushRequest,
    DocumentPushResponse,
    DocumentUploadResponse,
)
from app.rag.chroma_store import DEPARTMENTS

logger = logging.getLogger(__name__)
router = APIRouter(tags=["documents"])


def _options_for(user: dict) -> list[DocumentOption]:
    return [DocumentOption(**o) for o in get_options(str(user.get("role") or "employee"))]


def _audit_doc(
    *,
    user: dict,
    intent: str,
    query: str,
    model_used: str,
    token_usage: dict,
    answer: str,
    department: str | None = "document",
) -> dict:
    costs = costs_for_query(
        model_used=model_used or "document_pipeline",
        token_usage=token_usage or {},
        from_cache=False,
        severity="routine",
        escalated=False,
    )
    try:
        append_event(
            {
                "user_id": user.get("id"),
                "user_email": user.get("email"),
                "user_role": user.get("role"),
                "query": query,
                "intent": intent,
                "department": department,
                "severity": "routine",
                "model_used": model_used or "document_pipeline",
                "input_tokens": costs["input_tokens"],
                "output_tokens": costs["output_tokens"],
                "cost_usd": costs["cost_usd"],
                "from_cache": False,
                "context_used": True,
                "answer_length": len(answer or ""),
                "sources": [],
            }
        )
    except Exception:
        logger.warning("document audit failed", exc_info=True)
    return costs


@router.post("/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(
    user: CurrentUser,
    file: UploadFile = File(...),
    session_id: str = Form(...),
) -> DocumentUploadResponse:
    settings = get_settings()
    email = str(user.get("email") or "")
    try:
        sid = ensure_session(session_id, email, title_seed=file.filename or "Document")
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    try:
        cleanup_old_document_files()
    except Exception:
        logger.warning("document file cleanup failed", exc_info=True)

    data = await file.read()
    max_bytes = int(settings.document_max_bytes or 10_485_760)
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail=f"File too large (max {max_bytes // (1024 * 1024)}MB)",
        )
    filename = file.filename or "document.txt"
    doc_id = str(uuid.uuid4())
    kind = preview_kind(filename)
    size_bytes = len(data)
    pages = count_pages(data, filename)
    try:
        raw = extract_text(data, filename)
        cleaned = clean_text(raw)
        save_file(sid, doc_id, filename, data)
        rel = file_relative_path(sid, doc_id, filename)
        meta = upsert_document(
            session_id=sid,
            user_email=email,
            filename=filename,
            text=cleaned,
            content_type=file.content_type,
            stored_path=rel,
            preview_kind_value=kind,
            doc_id=doc_id,
        )
    except UnsupportedDocumentType as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmptyDocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("document upload failed")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {exc}") from exc

    options = _options_for(user)
    suggested = None
    if str(user.get("role") or "").lower() == "admin":
        try:
            suggested = suggest_department(cleaned, filename)
        except Exception:
            suggested = "hr"

    try:
        save_message(
            session_id=sid,
            user_email=email,
            role="user",
            content=f"Uploaded document: {filename}",
            department="document",
        )
        save_message(
            session_id=sid,
            user_email=email,
            role="assistant",
            content=(
                "I've read your document. Here are the things I can do with it:"
            ),
            department="document",
        )
    except Exception:
        logger.warning("document upload chat persist failed", exc_info=True)

    return DocumentUploadResponse(
        doc_id=str(meta["doc_id"]),
        filename=str(meta["filename"]),
        char_count=int(meta["char_count"]),
        session_id=sid,
        available_options=options,
        suggested_department=suggested,
        preview_kind=kind,
        file_size_bytes=size_bytes,
        page_count=pages,
    )


@router.get("/documents/active", response_model=DocumentActiveResponse | None)
def active_document(
    user: CurrentUser,
    session_id: str,
    include_text: bool = False,
) -> DocumentActiveResponse | None:
    email = str(user.get("email") or "")
    doc = get_active_document(session_id, email, include_text=include_text)
    if not doc:
        return None
    suggested = None
    if str(user.get("role") or "").lower() == "admin":
        full = doc if include_text and doc.get("text") else get_active_document(
            session_id, email, include_text=True
        )
        if full and full.get("text"):
            suggested = suggest_department(str(full["text"]), str(full.get("filename") or ""))
    size_bytes = None
    stored = doc.get("stored_path")
    if stored:
        try:
            path = absolute_path(str(stored))
            if path.is_file():
                size_bytes = path.stat().st_size
        except Exception:
            size_bytes = None
    return DocumentActiveResponse(
        doc_id=str(doc["doc_id"]),
        filename=str(doc["filename"]),
        char_count=int(doc["char_count"] or 0),
        created_at=str(doc["created_at"]),
        expires_at=str(doc.get("file_expires_at") or doc["expires_at"]),
        available_options=_options_for(user),
        suggested_department=suggested,
        preview_kind=doc.get("preview_kind"),
        file_size_bytes=size_bytes,
        text=str(doc["text"]) if include_text and doc.get("text") else None,
        text_expired=bool(doc.get("text_expired")) if include_text else False,
    )


@router.get("/documents/preview")
def preview_document(
    user: CurrentUser,
    session_id: str,
    doc_id: str,
) -> Response:
    email = str(user.get("email") or "")
    meta = get_document_for_preview(session_id, doc_id, email)
    if not meta:
        owner = document_owner_email(session_id, doc_id)
        if owner and owner != (email or "").strip().lower():
            raise HTTPException(status_code=403, detail="Not allowed to preview this document")
        raise HTTPException(status_code=404, detail="Document not found")
    stored = meta.get("stored_path")
    if not stored:
        raise HTTPException(status_code=404, detail="Original file not available")
    try:
        path = absolute_path(str(stored))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File missing on disk")

    kind = (meta.get("preview_kind") or preview_kind(str(meta.get("filename") or ""))).lower()
    fname = str(meta.get("filename") or path.name)
    if kind == "html":
        try:
            html_path = ensure_docx_preview_html(path)
        except Exception as exc:
            logger.exception("docx preview convert failed")
            raise HTTPException(status_code=500, detail=f"Preview failed: {exc}") from exc
        return HTMLResponse(
            content=html_path.read_text(encoding="utf-8"),
            headers={"Cache-Control": "private, max-age=60"},
        )
    if kind == "pdf":
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=fname,
            content_disposition_type="inline",
            headers={"Cache-Control": "private, max-age=60"},
        )
    return FileResponse(
        path,
        media_type="text/plain; charset=utf-8",
        filename=fname,
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=60"},
    )


@router.delete("/documents/active")
def delete_active_document(user: CurrentUser, session_id: str) -> dict:
    email = str(user.get("email") or "")
    ok = clear_document(session_id, email)
    if not ok:
        raise HTTPException(status_code=404, detail="No document to clear")
    return {"status": "ok"}


@router.post("/documents/analyze", response_model=DocumentAnalyzeResponse)
def analyze(req: DocumentAnalyzeRequest, user: CurrentUser) -> DocumentAnalyzeResponse:
    email = str(user.get("email") or "")
    role = str(user.get("role") or "employee")
    op = (req.operation or "").strip().lower()
    if op == "push_to_kb":
        raise HTTPException(
            status_code=400,
            detail="Use /documents/push-to-kb for knowledge base ingestion",
        )
    if not is_allowed_operation(role, op):
        raise HTTPException(status_code=403, detail="Operation not allowed for this role")

    try:
        sid = ensure_session(req.session_id, email)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    doc = get_active_document(sid, email, include_text=True)
    if not doc:
        raise HTTPException(
            status_code=404,
            detail="No active document for this session. Upload a file first.",
        )
    if not doc.get("text"):
        raise HTTPException(
            status_code=404,
            detail="Document text has expired. Re-upload the file to analyze it.",
        )

    try:
        analysis = analyze_document(
            text=str(doc["text"]),
            operation=op,
            question=req.question,
            filename=str(doc.get("filename") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("analyze failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    costs = _audit_doc(
        user=user,
        intent=f"document_{op}",
        query=f"{op}:{doc.get('filename')}"
        + (f" | {req.question}" if req.question else ""),
        model_used=analysis.model_used,
        token_usage=analysis.token_usage,
        answer=analysis.result,
    )

    try:
        label = op.replace("_", " ")
        save_message(
            session_id=sid,
            user_email=email,
            role="user",
            content=req.question.strip() if op == "ask" and req.question else f"Document: {label}",
            department="document",
        )
        save_message(
            session_id=sid,
            user_email=email,
            role="assistant",
            content=analysis.result,
            department="document",
            cost_usd=float(costs.get("cost_usd") or 0),
        )
    except Exception:
        logger.warning("document analyze chat persist failed", exc_info=True)

    return DocumentAnalyzeResponse(
        operation=analysis.operation,
        result=analysis.result,
        doc_id=str(doc["doc_id"]),
        filename=str(doc["filename"]),
        model_used=analysis.model_used,
        token_usage=dict(analysis.token_usage or {}),
        cost_usd=float(costs.get("cost_usd") or 0),
        session_id=sid,
    )


@router.post("/documents/push-to-kb", response_model=DocumentPushResponse)
def push_document_to_kb(req: DocumentPushRequest, user: AdminUser) -> DocumentPushResponse:
    email = str(user.get("email") or "")
    dept = (req.department or "").strip().lower()
    if dept not in DEPARTMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"department must be one of: {', '.join(DEPARTMENTS)}",
        )
    try:
        sid = ensure_session(req.session_id, email)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    doc = get_active_document(sid, email, include_text=True)
    if not doc or not doc.get("text"):
        raise HTTPException(status_code=404, detail="No active document for this session")

    result = push_to_kb(
        text=str(doc["text"]),
        filename=str(doc.get("filename") or "document"),
        department=dept,
        uploaded_by=user,
        title=req.title,
    )
    if not result.ok:
        raise HTTPException(status_code=409 if "duplicate" in (result.error or "").lower() else 400,
                            detail=result.error or "KB push failed")

    try:
        save_message(
            session_id=sid,
            user_email=email,
            role="user",
            content=f"Add to KB ({dept}): {doc.get('filename')}",
            department="document",
        )
        save_message(
            session_id=sid,
            user_email=email,
            role="assistant",
            content=(
                f"Added {doc.get('filename')} to the {dept} knowledge base "
                f"({result.chunks_created} chunk(s))."
            ),
            department="document",
        )
    except Exception:
        logger.warning("kb push chat persist failed", exc_info=True)

    return DocumentPushResponse(
        chunks_created=result.chunks_created,
        department=result.department,
        doc_ids=list(result.doc_ids),
        filename=str(doc.get("filename") or ""),
    )
