"""Retriever agent — fetches top-k chunks; unknown dept searches all KBs."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.agents.timing import ensure_timings, timed
from app.audit.query_trace import tracer_from_state
from app.config import get_settings
from app.rag.chroma_store import DEPARTMENTS, get_store

logger = logging.getLogger(__name__)


def _filter_relevant(chunks: List[Dict[str, Any]], max_distance: float) -> List[Dict[str, Any]]:
    kept: List[Dict[str, Any]] = []
    for chunk in chunks:
        dist = chunk.get("distance")
        if dist is None:
            kept.append(chunk)
            continue
        if float(dist) <= max_distance:
            kept.append(chunk)
    kept.sort(key=lambda c: float(c["distance"]) if c.get("distance") is not None else 0.0)
    return kept


def _retrieve_all_departments(query: str, top_k: int) -> List[Dict[str, Any]]:
    store = get_store()
    pooled: List[Dict[str, Any]] = []
    for dept in DEPARTMENTS:
        pooled.extend(store.query(dept, query, top_k=top_k))
    return pooled


def retrieve_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """LangGraph node: retrieve from one dept, or all depts when classification is unknown."""
    timings = ensure_timings(state)
    tracer = tracer_from_state(state)
    if tracer:
        dept_hint = state.get("department") or "unknown"
        tracer.agent_started("RETRIEVER", f"Retrieving KB chunks (dept={dept_hint})")
    with timed(timings, "retrieve"):
        settings = get_settings()
        department = (state.get("department") or "hr").lower()
        query = state.get("normalized_query") or state.get("query") or ""
        top_k = settings.retrieval_top_k
        max_distance = settings.retrieval_max_distance
        store = get_store()

        searched_all = department == "unknown"
        if searched_all:
            raw = _retrieve_all_departments(query, top_k=top_k)
            chunks = _filter_relevant(raw, max_distance)[:top_k]
            attempted = list(DEPARTMENTS)
            # No reclassify loop after a full-KB miss
            retry_count = max(int(state.get("retry_count") or 0), settings.retrieve_max_retries)
            if chunks:
                department = (chunks[0].get("department") or "unknown").lower()
                logger.info(
                    "retrieve all-KB hit best_dept=%s distance=%s chunks=%d",
                    department,
                    chunks[0].get("distance"),
                    len(chunks),
                )
            else:
                logger.info("retrieve all-KB miss — not recognized in any collection")
        else:
            raw = store.query(department, query, top_k=top_k)
            chunks = _filter_relevant(raw, max_distance)
            attempted = list(state.get("attempted_depts") or [])
            if department and department not in attempted:
                attempted.append(department)
            retry_count = int(state.get("retry_count") or 0)
            if not chunks:
                retry_count += 1
                logger.info(
                    "retrieve empty/irrelevant dept=%s retry_count=%s",
                    department,
                    retry_count,
                )
            else:
                logger.info(
                    "retrieve ok dept=%s chunks=%d best_distance=%s",
                    department,
                    len(chunks),
                    chunks[0].get("distance"),
                )

        sources = [c.get("title") or c.get("id") or "" for c in chunks]
        if tracer:
            top_score = 0.0
            if chunks:
                dist = chunks[0].get("distance")
                top_score = 1.0 - float(dist) if dist is not None else 0.0
            tracer.kb_retrieved(department, len(chunks), top_score)
            tracer.agent_done(
                "RETRIEVER",
                f"{len(chunks)} chunks from {department}",
            )
        updates: Dict[str, Any] = {
            "chunks": chunks,
            "sources": sources,
            "attempted_depts": attempted,
            "retry_count": retry_count,
            "context_used": bool(chunks),
            "node_timings": timings,
        }
        if searched_all and chunks:
            updates["department"] = department
        return updates


def retrieve(department: str, query: str, top_k: int | None = None) -> List[Dict[str, Any]]:
    """Standalone helper for Phase 2 testing without the graph."""
    store = get_store()
    return store.query(department, query, top_k=top_k)
