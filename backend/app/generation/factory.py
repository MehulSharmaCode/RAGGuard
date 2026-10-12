"""Select the configured generation provider. There is no automatic failover:
if the selected provider fails, the error is reported, never silently rerouted."""

from __future__ import annotations

from app.core.config import Settings
from app.core.errors import ConfigurationError
from app.generation.base import GenerationProvider
from app.generation.gemini import GeminiProvider
from app.generation.ollama import OllamaProvider


def build_provider(settings: Settings) -> GenerationProvider:
    if settings.generation_provider == "ollama":
        return OllamaProvider(
            settings.ollama_base_url,
            settings.ollama_model,
            timeout_seconds=settings.ollama_timeout_seconds,
            temperature=settings.generation_temperature,
        )
    if settings.generation_provider == "gemini":
        return GeminiProvider(
            settings.gemini_api_key,
            settings.gemini_model,
            temperature=settings.generation_temperature,
        )
    raise ConfigurationError(f"Unsupported GENERATION_PROVIDER: {settings.generation_provider!r}")
