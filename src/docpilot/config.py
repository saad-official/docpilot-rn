"""Runtime configuration, read once from the environment or `.env`.

Every secret is a `SecretStr`, so logging the settings object (or an exception that renders
it) prints `**********` instead of a key. A missing key degrades a feature rather than
crashing import: no Voyage key -> Gemini embeddings and no rerank; no Groq key -> Gemini
generates; no DATABASE_URL -> the in-memory store (tests and local experiments only).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from llm_kit import Settings as LLMSettings
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

EmbeddingProviderName = Literal["auto", "gemini", "voyage"]


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- storage ------------------------------------------------------------------
    # Pooled Neon URL for the API; ingestion and migrations may use the direct URL
    # (DATABASE_DIRECT_URL) because PgBouncer's transaction mode and long COPY-like
    # batches do not mix well.
    database_url: SecretStr | None = None
    database_direct_url: SecretStr | None = None

    # --- GitHub (ingestion only) ----------------------------------------------------
    github_token: SecretStr | None = None

    # --- model providers ----------------------------------------------------------
    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    openrouter_api_key: SecretStr | None = None
    voyage_api_key: SecretStr | None = None
    ollama_base_url: str = "http://localhost:11434/v1"

    # --- embeddings ---------------------------------------------------------------
    # "auto": Voyage when VOYAGE_API_KEY is set, otherwise Gemini. A corpus records the
    # model it was embedded with; the query side refuses to mix models (see retrieval).
    embedding_provider: EmbeddingProviderName = "auto"
    # Dimension of `chunks.embedding`, fixed when the migration runs. 768 for
    # gemini-embedding-001 (Matryoshka-truncated), 1024 for voyage-4-lite.
    embedding_dimensions: int = Field(default=768, ge=64, le=4096)
    embed_batch_size: int = Field(default=100, ge=1, le=100)
    # Batches are also bounded by estimated tokens, and paced to a tokens-per-minute
    # ceiling (Gemini's free tier rejects a single ~36k-token batch outright).
    embed_batch_tokens: int = Field(default=20_000, ge=500)
    embed_tpm: int = Field(default=25_000, ge=0)  # 0 = no pacing (paid tiers)
    # Seconds to wait between embedding batches (free-tier pacing).
    embed_pause_s: float = Field(default=1.0, ge=0)

    # --- retrieval ------------------------------------------------------------------
    rerank: bool = True  # only takes effect when VOYAGE_API_KEY is set
    context_token_budget: int = Field(default=6000, ge=500, le=30000)

    # --- API ----------------------------------------------------------------------
    web_origin: str = "http://localhost:3000,http://localhost:3600"
    port: int = 7861
    questions_per_hour_per_ip: int = 30
    trust_proxy_headers: bool = False
    ip_hash_salt: SecretStr = SecretStr("docpilot-rn")
    vercel: bool = False
    cron_secret: SecretStr | None = None
    # A corpus older than this is reported as stale by /api/health.
    corpus_max_age_days: int = 45

    # --- observability (optional) ---------------------------------------------------
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    log_level: str = "INFO"

    @property
    def web_origins(self) -> list[str]:
        return [origin.strip() for origin in self.web_origin.split(",") if origin.strip()]

    def llm_settings(self) -> LLMSettings:
        """llm-kit settings built from *this* project's config (not the workspace .env)."""
        return LLMSettings(
            gemini_api_key=self.gemini_api_key,
            groq_api_key=self.groq_api_key,
            openrouter_api_key=self.openrouter_api_key,
            ollama_base_url=self.ollama_base_url,
        )

    def has_key(self, provider: str) -> bool:
        secret = getattr(self, f"{provider}_api_key", None)
        return bool(secret and secret.get_secret_value())

    def dsn(self, *, direct: bool = False) -> str | None:
        """The connection string to use. `direct=True` prefers DATABASE_DIRECT_URL."""
        for secret in (
            (self.database_direct_url, self.database_url) if direct else (self.database_url,)
        ):
            if secret is not None and secret.get_secret_value():
                return secret.get_secret_value()
        return None

    @property
    def resolved_embedding_provider(self) -> Literal["gemini", "voyage"]:
        if self.embedding_provider != "auto":
            return self.embedding_provider
        return "voyage" if self.has_key("voyage") else "gemini"


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()
