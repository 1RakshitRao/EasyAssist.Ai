from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # anthropic | ollama
    llm_provider: str = "ollama"
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_timeout_seconds: float = 120.0

    # Role → model. Defaults simulate Haiku / Sonnet / Opus on local Ollama.
    # Anthropic: set LLM_PROVIDER=anthropic and use claude-* model ids.
    classifier_model: str = "llama3.2:latest"  # Haiku role
    answer_model_routine: str = "llama3.2:latest"  # Haiku role
    answer_model_high: str = "mistral:latest"  # Sonnet role
    answer_model_opus: str = "llama3.1:8b"  # Opus role

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
    document_ttl_seconds: int = 7200  # 2 hours

    @property
    def escalate_department_list(self) -> List[str]:
        return [d.strip().lower() for d in self.escalate_departments.split(",") if d.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
