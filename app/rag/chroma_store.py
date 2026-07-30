"""ChromaDB store with four department collections and seed loading."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings
from app.rag.embeddings import embed_query, embed_texts

logger = logging.getLogger(__name__)

DEPARTMENTS = ("hr", "it", "compliance", "legal")
SEED_DIR = Path(__file__).resolve().parent / "seed_docs"


class NearDuplicateError(ValueError):
    """Raised when an ingest/promote doc is too similar to an existing KB entry."""

    def __init__(self, match: Dict[str, Any]) -> None:
        self.match = match
        super().__init__(
            f"Near-duplicate of {match.get('id')} "
            f"(title={match.get('title')!r}, distance={match.get('distance')})"
        )


class ChromaStore:
    def __init__(self, persist_dir: Optional[str] = None) -> None:
        settings = get_settings()
        path = persist_dir or settings.chroma_persist_dir
        Path(path).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collections = {
            dept: self._client.get_or_create_collection(
                name=f"helpdesk_{dept}",
                metadata={"department": dept},
            )
            for dept in DEPARTMENTS
        }

    def collection_counts(self) -> Dict[str, int]:
        return {dept: col.count() for dept, col in self._collections.items()}

    def seed_if_empty(self) -> None:
        counts = self.collection_counts()
        if all(c > 0 for c in counts.values()):
            logger.info("Chroma collections already seeded: %s", counts)
            return
        logger.info("Seeding Chroma from %s", SEED_DIR)
        for dept in DEPARTMENTS:
            seed_path = SEED_DIR / f"{dept}.json"
            if not seed_path.exists():
                logger.warning("Missing seed file: %s", seed_path)
                continue
            docs = json.loads(seed_path.read_text(encoding="utf-8"))
            if self._collections[dept].count() == 0:
                self.add_documents(dept, docs, check_duplicates=False)

    def find_near_duplicate(
        self,
        department: str,
        title: str,
        content: str,
        *,
        max_distance: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Return the closest existing doc if it is a near-duplicate.

        Checks:
        1) case-insensitive exact title match in the department collection
        2) embedding L2 distance against the nearest neighbor
        """
        dept = department.lower().strip()
        if dept not in self._collections:
            raise ValueError(f"Unknown department: {department}")
        col = self._collections[dept]
        if col.count() == 0:
            return None

        title_key = (title or "").strip().casefold()
        if title_key:
            raw = col.get(include=["metadatas", "documents"])
            ids = raw.get("ids") or []
            metas = raw.get("metadatas") or []
            docs = raw.get("documents") or []
            for i, doc_id in enumerate(ids):
                meta = (metas[i] if i < len(metas) else None) or {}
                existing_title = str(meta.get("title") or "").strip().casefold()
                if existing_title and existing_title == title_key:
                    return {
                        "id": doc_id,
                        "title": meta.get("title") or "",
                        "department": dept,
                        "distance": 0.0,
                        "reason": "exact_title",
                        "content_preview": (docs[i] if i < len(docs) else "")[:200],
                    }

        text = f"{(title or '').strip()}\n\n{(content or '').strip()}".strip()
        if not text:
            return None

        threshold = (
            float(max_distance)
            if max_distance is not None
            else float(get_settings().ingest_dedup_max_distance)
        )
        embedding = embed_query(text)
        result = col.query(
            query_embeddings=[embedding],
            n_results=1,
            include=["documents", "metadatas", "distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        docs = (result.get("documents") or [[]])[0]
        if not ids:
            return None

        distance = float(dists[0])
        if distance > threshold:
            logger.info(
                "ingest dedup miss dept=%s distance=%.4f threshold=%.4f",
                dept,
                distance,
                threshold,
            )
            return None

        meta = metas[0] or {}
        logger.info(
            "ingest dedup hit dept=%s id=%s distance=%.4f title=%r",
            dept,
            ids[0],
            distance,
            meta.get("title"),
        )
        return {
            "id": ids[0],
            "title": meta.get("title") or "",
            "department": dept,
            "distance": round(distance, 4),
            "reason": "embedding_near_duplicate",
            "content_preview": (docs[0] if docs else "")[:200],
        }

    def add_documents(
        self,
        department: str,
        docs: List[Dict[str, Any]],
        *,
        check_duplicates: bool = True,
    ) -> List[str]:
        """
        Upsert docs into a department KB.

        When check_duplicates=True (default), raises NearDuplicateError on the
        first near-duplicate instead of inserting it.
        """
        dept = department.lower().strip()
        if dept not in self._collections:
            raise ValueError(f"Unknown department: {department}")
        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []
        for doc in docs:
            title = doc.get("title", "Untitled")
            content = doc.get("content", "")
            if check_duplicates:
                match = self.find_near_duplicate(dept, title, content)
                if match:
                    raise NearDuplicateError(match)
            doc_id = doc.get("id") or str(uuid.uuid4())
            text = f"{title}\n\n{content}".strip()
            meta = {"title": title, "department": dept}
            extra = doc.get("metadata") or {}
            meta.update({k: str(v) for k, v in extra.items()})
            ids.append(doc_id)
            documents.append(text)
            metadatas.append(meta)
        embeddings = embed_texts(documents)
        self._collections[dept].upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings,
        )
        logger.info("Upserted %d docs into %s", len(ids), dept)
        return ids

    def query(
        self,
        department: str,
        query_text: str,
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        dept = department.lower().strip()
        if dept not in self._collections:
            return []
        k = top_k or get_settings().retrieval_top_k
        if self._collections[dept].count() == 0:
            return []
        embedding = embed_query(query_text)
        result = self._collections[dept].query(
            query_embeddings=[embedding],
            n_results=min(k, self._collections[dept].count()),
            include=["documents", "metadatas", "distances"],
        )
        chunks: List[Dict[str, Any]] = []
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        dists = (result.get("distances") or [[]])[0]
        ids = (result.get("ids") or [[]])[0]
        for i, doc in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            chunks.append(
                {
                    "id": ids[i] if i < len(ids) else "",
                    "content": doc,
                    "title": (meta or {}).get("title", ""),
                    "department": dept,
                    "distance": dists[i] if i < len(dists) else None,
                    "metadata": meta or {},
                }
            )
        return chunks

    def list_documents(self, department: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """Return official docs/protocols stored in each department KB."""
        depts = [department.lower().strip()] if department else list(DEPARTMENTS)
        out: Dict[str, List[Dict[str, Any]]] = {}
        for dept in depts:
            if dept not in self._collections:
                continue
            col = self._collections[dept]
            if col.count() == 0:
                out[dept] = []
                continue
            raw = col.get(include=["documents", "metadatas"])
            ids = raw.get("ids") or []
            docs = raw.get("documents") or []
            metas = raw.get("metadatas") or []
            items: List[Dict[str, Any]] = []
            for i, doc_id in enumerate(ids):
                meta = (metas[i] if i < len(metas) else None) or {}
                title = meta.get("title") or "Untitled"
                full = docs[i] if i < len(docs) else ""
                # Stored as "title\n\ncontent"
                body = full
                if full.startswith(title):
                    body = full[len(title) :].lstrip("\n")
                items.append(
                    {
                        "id": doc_id,
                        "title": title,
                        "content": body.strip(),
                        "department": dept,
                    }
                )
            items.sort(key=lambda d: (d.get("title") or "").lower())
            out[dept] = items
        return out


_store: Optional[ChromaStore] = None


def get_store() -> ChromaStore:
    global _store
    if _store is None:
        _store = ChromaStore()
    return _store
