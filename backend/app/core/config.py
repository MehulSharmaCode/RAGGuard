"""Typed application settings loaded from environment variables and `.env`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[3]

GenerationProviderName = Literal["ollama", "gemini"]


class Settings(BaseSettings):
    """All runtime configuration. Every field maps to an upper-case env variable."""

    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---------------------------------------------------------
    app_env: str = "development"
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    log_level: str = "INFO"

    # --- Generation ----------------------------------------------------------
    generation_provider: GenerationProviderName = "ollama"
    generation_temperature: float = Field(default=0.1, ge=0.0, le=2.0)

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:9b"
    ollama_timeout_seconds: float = Field(default=180.0, gt=0)

    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-2.5-flash"

    # --- Embeddings ----------------------------------------------------------
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # --- Vector store --------------------------------------------------------
    qdrant_url: str | None = None
    qdrant_api_key: SecretStr | None = None
    qdrant_local_path: Path = REPO_ROOT / "qdrant_storage"
    qdrant_collection_name: str = Field(default="ragguard_chunks", min_length=1)

    # --- Ingestion and retrieval ---------------------------------------------
    chunk_size_tokens: int = Field(default=180, ge=16, le=512)
    chunk_overlap_tokens: int = Field(default=30, ge=0)
    default_top_k: int = Field(default=4, ge=1, le=20)
    max_upload_size_mb: float = Field(default=10.0, gt=0, le=100)
    min_retrieval_score: float = Field(default=0.35, ge=-1.0, le=1.0)

    @field_validator("qdrant_url", "gemini_api_key", "qdrant_api_key", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("qdrant_local_path", mode="after")
    @classmethod
    def _resolve_local_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else REPO_ROOT / value

    @model_validator(mode="after")
    def _check_chunking(self) -> Settings:
        if self.chunk_overlap_tokens >= self.chunk_size_tokens:
            raise ValueError("CHUNK_OVERLAP_TOKENS must be smaller than CHUNK_SIZE_TOKENS")
        return self

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_size_mb * 1024 * 1024)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
