"""Local generation through the Ollama HTTP API (non-streaming /api/chat)."""

from __future__ import annotations

import logging
import re

import httpx

from app.core.errors import (
    GenerationTimeoutError,
    GenerationUnavailableError,
    GenerationUpstreamError,
)
from app.generation.base import ProviderStatus

logger = logging.getLogger(__name__)

# Defensive: strip reasoning blocks if a model emits them despite think=false.
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class OllamaProvider:
    name = "ollama"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_seconds: float,
        temperature: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self._temperature = temperature
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds, connect=5.0),
            transport=transport,
        )

    def _unreachable(self, exc: Exception) -> GenerationUnavailableError:
        logger.warning("Ollama unreachable at %s: %s", self._client.base_url, exc)
        return GenerationUnavailableError(
            "The Ollama service is not reachable. Start it with `ollama serve` "
            "and check OLLAMA_BASE_URL."
        )

    def _model_missing(self) -> GenerationUnavailableError:
        return GenerationUnavailableError(
            f"The Ollama model '{self.model}' is not installed. "
            f"Install it with `ollama pull {self.model}` or change OLLAMA_MODEL."
        )

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "think": False,
            "options": {"temperature": self._temperature},
        }
        try:
            response = self._client.post("/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            if isinstance(exc, httpx.ConnectTimeout):
                raise self._unreachable(exc) from exc
            logger.warning("Ollama generation timed out: %s", exc)
            raise GenerationTimeoutError("The local model did not respond in time.") from exc
        except httpx.TransportError as exc:
            raise self._unreachable(exc) from exc

        if response.status_code == 404:
            raise self._model_missing()
        if response.status_code >= 400:
            logger.warning("Ollama returned HTTP %d: %s", response.status_code, response.text[:500])
            raise GenerationUpstreamError(
                f"The Ollama service returned an error (HTTP {response.status_code})."
            )
        try:
            content = response.json()["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise GenerationUpstreamError(
                "The Ollama service returned a malformed response."
            ) from exc

        answer = _THINK_BLOCK.sub("", str(content)).strip()
        if not answer:
            raise GenerationUpstreamError("The local model returned an empty answer.")
        return answer

    def check_readiness(self) -> ProviderStatus:
        """Check the service and that the model is installed, via /api/tags (no generation)."""
        try:
            response = self._client.get("/api/tags", timeout=3.0)
            response.raise_for_status()
            installed = {m.get("name") for m in response.json().get("models", [])}
        except (httpx.HTTPError, ValueError) as exc:
            logger.info("Ollama readiness check failed: %s", exc)
            return ProviderStatus("unavailable", "The Ollama service is not reachable.")
        candidates = {self.model, f"{self.model}:latest"}
        if installed.isdisjoint(candidates):
            return ProviderStatus("model_missing", f"Model '{self.model}' is not installed.")
        return ProviderStatus("ready", f"Model '{self.model}' is installed.")

    def close(self) -> None:
        self._client.close()
