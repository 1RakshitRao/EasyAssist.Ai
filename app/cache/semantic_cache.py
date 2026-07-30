"""Semantic FAQ cache — Chroma vector similarity (cosine) over MiniLM embeddings."""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings
from app.rag.embeddings import embed_query

logger = logging.getLogger(__name__)

COLLECTION_NAME = "helpdesk_semantic_cache"


class SemanticCache:
    """
    Embed queries and match prior answers by cosine similarity.
    Chroma cosine space returns distance = 1 - similarity.
    """

    def __init__(self, persist_dir: Optional[str] = None) -> None:
        settings = get_settings()
        path = persist_dir or settings.chroma_persist_dir
        Path(path).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={
                "hnsw:space": "cosine",
                "purpose": "faq_semantic_cache",
            },
        )
        self.backend = "chroma_semantic"
        self.threshold = float(settings.semantic_cache_threshold)
        logger.info(
            "Semantic cache ready collection=%s threshold=%.2f count=%d",
            COLLECTION_NAME,
            self.threshold,
            self._collection.count(),
        )

    def count(self) -> int:
        return self._collection.count()

    def clear(self) -> None:
        """Drop all cached FAQ answers (keeps collection schema)."""
        ids = self._collection.get(include=[]).get("ids") or []
        if ids:
            self._collection.delete(ids=ids)
        logger.info("Semantic cache cleared (%d entries removed)", len(ids))

    def lookup(
        self,
        query_text: str,
        department_hint: Optional[str] = None,
    ) -> Tuple[Optional[Dict[str, Any]], float]:
        """
        Returns (payload, similarity). payload is None on miss.
        """
        if self._collection.count() == 0:
            return None, 0.0

        text = (query_text or "").strip()
        if not text:
            return None, 0.0

        embedding = embed_query(text)
        result = self._collection.query(
            query_embeddings=[embedding],
            n_results=1,
            include=["documents", "metadatas", "distances"],
        )
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        if not docs:
            return None, 0.0

        distance = float(dists[0])
        similarity = 1.0 - distance
        meta = metas[0] or {}

        # Optional TTL
        ttl = get_settings().cache_ttl_seconds
        created_at = float(meta.get("created_at") or 0)
        if created_at and ttl > 0 and (time.time() - created_at) > ttl:
            logger.info("Semantic cache entry expired (age > TTL)")
            return None, similarity

        hint = (department_hint or "").strip().lower()
        cached_hint = (meta.get("department_hint") or "").strip().lower()
        if hint and cached_hint and hint != cached_hint:
            logger.info(
                "Semantic near-match skipped (hint mismatch %s vs %s) sim=%.3f",
                hint,
                cached_hint,
                similarity,
            )
            return None, similarity

        if similarity < self.threshold:
            logger.info(
                "Semantic cache MISS similarity=%.3f threshold=%.2f",
                similarity,
                self.threshold,
            )
            return None, similarity

        try:
            payload = json.loads(docs[0])
        except json.JSONDecodeError:
            logger.warning("Semantic cache document was not valid JSON")
            return None, similarity

        logger.info(
            "Semantic cache HIT similarity=%.3f matched=%r",
            similarity,
            meta.get("normalized_query"),
        )
        return payload, similarity

    def store(
        self,
        query_text: str,
        payload: Dict[str, Any],
        department_hint: Optional[str] = None,
    ) -> str:
        text = (query_text or "").strip()
        embedding = embed_query(text)
        doc_id = str(uuid.uuid4())
        self._collection.upsert(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[json.dumps(payload)],
            metadatas=[
                {
                    "normalized_query": text[:500],
                    "department_hint": (department_hint or "").strip().lower(),
                    "created_at": time.time(),
                    "department": str(payload.get("department") or ""),
                }
            ],
        )
        logger.info("Semantic cache STORE id=%s query=%r", doc_id, text[:80])
        return doc_id


_semantic: Optional[SemanticCache] = None


def get_semantic_cache() -> SemanticCache:
    global _semantic
    if _semantic is None:
        _semantic = SemanticCache()
    return _semantic
