"""Health endpoint."""

from __future__ import annotations

from typing import Dict

from fastapi import APIRouter

from app.cache.redis_cache import get_cache
from app.cache.semantic_cache import get_semantic_cache
from app.config import get_settings
from app.models.schemas import HealthResponse
from app.rag.chroma_store import get_store
from app.tickets.store import list_tickets

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    cache = get_cache()
    store = get_store()
    sem_count = 0
    try:
        if settings.semantic_cache_enabled:
            sem_count = get_semantic_cache().count()
    except Exception:
        sem_count = -1
    models_block: Dict[str, str] = {
        "provider": settings.llm_provider,
        "embedding": settings.embedding_model,
        "semantic_cache_threshold": str(settings.semantic_cache_threshold),
    }
    if settings.llm_provider.lower() == "groq":
        models_block.update(
            {
                "tier_fast": settings.groq_model_fast,
                "tier_balanced": settings.groq_model_balanced,
                "tier_powerful": settings.groq_model_powerful,
                "tier_guardrails": settings.groq_model_guardrails,
            }
        )
    elif settings.llm_provider.lower() == "grok":
        models_block.update(
            {
                "tier_fast": settings.grok_model_fast,
                "tier_balanced": settings.grok_model_balanced,
                "tier_powerful": settings.grok_model_powerful,
            }
        )
    else:
        models_block.update(
            {
                "classifier_haiku": settings.classifier_model,
                "answer_routine_haiku": settings.answer_model_routine,
                "answer_high_sonnet": settings.answer_model_high,
                "answer_escalated_opus": settings.answer_model_opus,
            }
        )

    return HealthResponse(
        status="ok",
        cache_backend=f"semantic_chroma({sem_count})+{cache.backend}",
        chroma_collections=store.collection_counts(),
        models=models_block,
        open_tickets=len(list_tickets(status="open")),
    )
