from functools import lru_cache
from typing import List

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_SUPPORTED_LLM_PROVIDERS = frozenset({"groq", "grok", "anthropic"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # groq | grok | anthropic (Ollama is not supported)
    llm_provider: str = "groq"
    groq_api_key: str = ""
    xai_api_key: str = ""
    anthropic_api_key: str = ""

    @field_validator("llm_provider")
    @classmethod
    def validate_llm_provider(cls, value: str) -> str:
        provider = (value or "groq").lower().strip()
        if provider == "ollama":
            raise ValueError(
                "LLM_PROVIDER=ollama is no longer supported. "
                "Use groq (default), grok, or anthropic."
            )
        if provider not in _SUPPORTED_LLM_PROVIDERS:
            raise ValueError(
                f"Unsupported LLM_PROVIDER: {provider!r}. "
                f"Supported: {', '.join(sorted(_SUPPORTED_LLM_PROVIDERS))}."
            )
        return provider

    # Groq tier models (default when LLM_PROVIDER=groq)
    groq_model_fast: str = "openai/gpt-oss-20b"
    groq_model_balanced: str = "openai/gpt-oss-120b"
    groq_model_powerful: str = "openai/gpt-oss-120b"
    groq_model_guardrails: str = "llama-prompt-guard-2-86m"

    # Grok tier models (when LLM_PROVIDER=grok)
    grok_model_fast: str = "grok-4.1-fast"
    grok_model_balanced: str = "grok-4.3"
    grok_model_powerful: str = "grok-4.6"

    # Anthropic role → model (when LLM_PROVIDER=anthropic)
    classifier_model: str = "claude-haiku-4-5"
    answer_model_routine: str = "claude-haiku-4-5"
    answer_model_high: str = "claude-sonnet-4-6"
    answer_model_opus: str = "claude-sonnet-4-6"

    # Groq list prices (USD / million tokens) for cost dashboard
    price_groq_fast_input_per_mtok: float = 0.075
    price_groq_fast_output_per_mtok: float = 0.30
    price_groq_balanced_input_per_mtok: float = 0.15
    price_groq_balanced_output_per_mtok: float = 0.60
    price_groq_powerful_input_per_mtok: float = 0.15
    price_groq_powerful_output_per_mtok: float = 0.60
    price_groq_guardrails_input_per_mtok: float = 0.04
    price_groq_guardrails_output_per_mtok: float = 0.04

    # Grok list prices (USD / million tokens) for cost dashboard
    price_grok_fast_input_per_mtok: float = 0.20
    price_grok_fast_output_per_mtok: float = 0.50
    price_grok_balanced_input_per_mtok: float = 1.25
    price_grok_balanced_output_per_mtok: float = 2.50
    price_grok_powerful_input_per_mtok: float = 2.00
    price_grok_powerful_output_per_mtok: float = 6.00

    redis_url: str = ""
    cache_ttl_seconds: int = 3600
    # Cosine similarity threshold for semantic FAQ cache (0–1).
    # With all-MiniLM-L6-v2, close paraphrases often land ~0.68–0.75;
    # 0.92 is stricter (near-duplicates only).
    semantic_cache_threshold: float = 0.70
    semantic_cache_enabled: bool = True

    retrieval_top_k: int = 4
    retrieve_max_retries: int = 1
    # Chroma L2 distance cutoff — chunks farther than this count as "not in KB"
    retrieval_max_distance: float = 1.15
    # Ingest / promote near-dup gate (Chroma default L2). Lower = stricter.
    # ~0.45 catches near-identical MiniLM paraphrases; exact title still blocked.
    ingest_dedup_max_distance: float = 0.45
    chroma_persist_dir: str = "./data/chroma"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    escalate_departments: str = "legal,hr"

    # Auth (local JWT)
    jwt_secret: str = "dev-only-change-me-ampcus-helpdesk"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480
    admin_email: str = "admin@ampcus.com"
    admin_password: str = "ChangeMeAdmin1!"
    users_path: str = ""

    # Audit / cost attribution / prompt scoring (SQLite)
    audit_db_path: str = ""
    prompt_score_window: int = 10
    prompt_score_restrict_avg: float = 4.0
    prompt_training_grace_days: int = 7
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "helpdesk@ampcus.com"
    training_base_url: str = "http://127.0.0.1:8080"
    app_base_url: str = "http://127.0.0.1:8080"
    ops_sla_hours: float = 24.0
    escalation_reminder_hours: float = 2.0
    escalation_reminder_poll_seconds: float = 60.0

    # Anthropic-equivalent list prices (USD / million tokens) for cost dashboard
    price_haiku_input_per_mtok: float = 1.0
    price_haiku_output_per_mtok: float = 5.0
    price_sonnet_input_per_mtok: float = 3.0
    price_sonnet_output_per_mtok: float = 15.0
    price_opus_input_per_mtok: float = 15.0
    price_opus_output_per_mtok: float = 75.0

    # Chat document assistant
    document_max_bytes: int = 10_485_760  # 10MB
    document_ttl_seconds: int = 7200  # 2 hours (extracted text)
    document_storage_dir: str = "./data/documents"
    document_file_ttl_days: int = 7  # original bytes on disk

    # Onboarding
    onboarding_hr_email: str = "hr-admin@ampcus.com"
    onboarding_reminder_hour: int = 9
    onboarding_reminder_poll_seconds: float = 300.0
    onboarding_window_days: int = 7

    # Guesthouse reservations
    reservation_hr_email: str = "hr@ampcus.com"
    reservation_reminder_hour: int = 9
    reservation_reminder_poll_seconds: float = 300.0
    reservation_auto_approve_hours: int = 24

    # Office infrastructure — IPP printing
    print_enabled: bool = True
    print_ipp_timeout_seconds: float = 30.0
    print_simulate_when_unreachable: bool = True

    # Conference room booking (Microsoft Graph)
    microsoft_tenant_id: str = ""
    microsoft_client_id: str = ""
    microsoft_client_secret: str = ""
    conference_room_booking_enabled: bool = False

    # News headlines (NewsAPI) for chat loading state
    newsapi_key: str = ""
    newsapi_cache_seconds: int = 900

    # Fun facts for chat loading state (JSON array or .txt one per line)
    fun_facts_path: str = "data/fun-facts.json"

    @property
    def escalate_department_list(self) -> List[str]:
        return [d.strip().lower() for d in self.escalate_departments.split(",") if d.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
