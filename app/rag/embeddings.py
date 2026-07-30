"""Local embedding model for Chroma (zero API cost)."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import List

from app.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def _load_model():
    from sentence_transformers import SentenceTransformer

    settings = get_settings()
    logger.info("Loading embedding model: %s", settings.embedding_model)
    return SentenceTransformer(settings.embedding_model)


def embed_texts(texts: List[str]) -> List[List[float]]:
    model = _load_model()
    vectors = model.encode(texts, normalize_embeddings=True)
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> List[float]:
    return embed_texts([text])[0]
