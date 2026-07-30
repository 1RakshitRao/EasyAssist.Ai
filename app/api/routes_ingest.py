"""Ingest endpoint — upsert documents into a department KB (admin only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException

from app.auth.deps import AdminUser
from app.models.schemas import IngestRequest, IngestResponse
from app.rag.chroma_store import DEPARTMENTS, NearDuplicateError, get_store

router = APIRouter(tags=["ingest"])


@router.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest, _admin: AdminUser) -> IngestResponse:
    dept = req.department.lower().strip()
    if dept not in DEPARTMENTS:
        raise HTTPException(
            status_code=400,
            detail=f"department must be one of: {', '.join(DEPARTMENTS)}",
        )
    doc_id = str(uuid.uuid4())
    store = get_store()
    try:
        store.add_documents(
            dept,
            [
                {
                    "id": doc_id,
                    "title": req.title,
                    "content": req.content,
                    "metadata": req.metadata or {},
                }
            ],
            check_duplicates=True,
        )
    except NearDuplicateError as exc:
        match = exc.match
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Near-duplicate document already exists in this knowledge base",
                "department": dept,
                "duplicate_of": match.get("id"),
                "duplicate_title": match.get("title"),
                "duplicate_distance": match.get("distance"),
                "reason": match.get("reason"),
            },
        ) from exc
    return IngestResponse(status="ok", department=dept, doc_id=doc_id)
