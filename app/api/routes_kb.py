"""Knowledge base listing — official docs/protocols by department."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.auth.deps import CurrentUser
from app.rag.chroma_store import DEPARTMENTS, get_store

router = APIRouter(tags=["knowledge-base"])


@router.get("/kb")
def list_knowledge_base(
    _user: CurrentUser,
    department: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Return official documents/protocols stored in the RAG knowledge bases."""
    if department:
        dept = department.lower().strip()
        if dept not in DEPARTMENTS:
            raise HTTPException(
                status_code=400,
                detail=f"department must be one of: {', '.join(DEPARTMENTS)}",
            )
    store = get_store()
    by_dept = store.list_documents(department)
    departments: List[Dict[str, Any]] = []
    for dept in DEPARTMENTS:
        if dept not in by_dept:
            continue
        docs = by_dept[dept]
        departments.append(
            {
                "department": dept,
                "count": len(docs),
                "documents": docs,
            }
        )
    return {
        "departments": departments,
        "total_documents": sum(d["count"] for d in departments),
    }
