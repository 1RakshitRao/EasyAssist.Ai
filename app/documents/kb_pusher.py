"""Admin path: push an uploaded document into a department KB."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.audit.store import append_event
from app.documents.chunker import chunk_text
from app.llm.client import complete, resolve_tier_model
from app.rag.chroma_store import DEPARTMENTS, NearDuplicateError, get_store

logger = logging.getLogger(__name__)

_DEPT_HINTS = {
    "hr": ("leave", "pto", "payroll", "hiring", "employee handbook", "benefits"),
    "it": ("password", "vpn", "laptop", "software", "access", "network", "email"),
    "compliance": ("policy", "audit", "soc2", "gdpr", "pci", "regulation"),
    "legal": ("contract", "agreement", "liability", "nda", "terms", "counsel"),
}


@dataclass
class PushResult:
    ok: bool
    department: str = ""
    chunks_created: int = 0
    doc_ids: List[str] = field(default_factory=list)
    error: str = ""
    suggested_department: str = ""


def suggest_department(text: str, filename: str = "") -> str:
    """Heuristic + optional Haiku suggestion; always returns a valid dept."""
    blob = f"{filename}\n{text[:4000]}".lower()
    scores = {d: 0 for d in DEPARTMENTS}
    for dept, words in _DEPT_HINTS.items():
        for w in words:
            if w in blob:
                scores[dept] += 1
    best = max(DEPARTMENTS, key=lambda d: scores[d])
    if scores[best] > 0:
        return best

    try:
        model = resolve_tier_model("balanced")
        result = complete(
            model=model,
            system=(
                "Classify the document into exactly one department: "
                "hr, it, compliance, or legal. Reply with only that word."
            ),
            user_content=f"Filename: {filename}\n\nExcerpt:\n{text[:3000]}",
            max_tokens=20,
        )
        word = re.sub(r"[^a-z]", "", (result.text or "").strip().lower())
        if word in DEPARTMENTS:
            return word
    except Exception:
        logger.warning("dept suggestion LLM failed", exc_info=True)
    return "hr"


def _title_stem(filename: str) -> str:
    return Path(filename or "document").stem or "document"


def push_to_kb(
    *,
    text: str,
    filename: str,
    department: str,
    uploaded_by: Dict[str, Any],
    title: Optional[str] = None,
    check_duplicates: bool = True,
) -> PushResult:
    dept = (department or "").strip().lower()
    if dept not in DEPARTMENTS:
        return PushResult(
            ok=False,
            error=f"department must be one of: {', '.join(DEPARTMENTS)}",
        )
    body = (text or "").strip()
    if not body:
        return PushResult(ok=False, error="empty document")

    chunks = chunk_text(body, source_name=filename)
    if not chunks:
        return PushResult(ok=False, error="no chunks produced")

    base_title = (title or "").strip() or _title_stem(filename)
    docs = []
    doc_ids: List[str] = []
    for i, chunk in enumerate(chunks, 1):
        doc_id = str(uuid.uuid4())
        doc_ids.append(doc_id)
        chunk_title = (
            base_title if len(chunks) == 1 else f"{base_title} (part {i}/{len(chunks)})"
        )
        docs.append(
            {
                "id": doc_id,
                "title": chunk_title,
                "content": chunk,
                "metadata": {
                    "source": "chat_document",
                    "filename": filename,
                    "chunk_index": i,
                    "chunk_total": len(chunks),
                    "uploaded_by": uploaded_by.get("email"),
                },
            }
        )

    store = get_store()
    try:
        store.add_documents(dept, docs[:1], check_duplicates=check_duplicates)
        if len(docs) > 1:
            store.add_documents(dept, docs[1:], check_duplicates=False)
    except NearDuplicateError as exc:
        match = exc.match or {}
        return PushResult(
            ok=False,
            department=dept,
            error=(
                "Near-duplicate already exists in this knowledge base "
                f"(title={match.get('title')!r})."
            ),
        )
    except Exception as exc:
        logger.exception("kb push failed")
        return PushResult(ok=False, department=dept, error=str(exc))

    try:
        append_event(
            {
                "user_id": uploaded_by.get("id"),
                "user_email": uploaded_by.get("email"),
                "user_role": uploaded_by.get("role"),
                "query": f"push_to_kb:{filename}",
                "intent": "document_kb_push",
                "department": dept,
                "severity": "routine",
                "model_used": "document_kb_pusher",
                "input_tokens": 0,
                "output_tokens": 0,
                "cost_usd": 0.0,
                "from_cache": False,
                "context_used": True,
                "answer_length": len(body),
                "sources": [filename],
            }
        )
    except Exception:
        logger.warning("kb push audit failed", exc_info=True)

    return PushResult(
        ok=True,
        department=dept,
        chunks_created=len(docs),
        doc_ids=doc_ids,
    )
