"""Optional hosted generation through Google Gemini (official `google-genai` SDK).

Never the default. The SDK client is created lazily, so a missing key only
produces an error when generation is actually attempted.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from pydantic import SecretStr

from app.core.errors import (
    GenerationConfigError,
    GenerationRateLimitError,
    GenerationTimeoutError,
    GenerationUnavailableError,
    GenerationUpstreamError,
)
from app.generation.base import ProviderStatus

logger = logging.getLogger(__name__)


class GeminiProvider:
    name = "gemini"

    def __init__(
        self,
        api_key: SecretStr | None,
        model: str,
        *,
        temperature: float,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._temperature = temperature
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            if self._api_key is None:
                raise GenerationConfigError(
                    "GENERATION_PROVIDER is 'gemini' but GEMINI_API_KEY is not set."
                )
            from google import genai

            self._client = genai.Client(api_key=self._api_key.get_secret_value())
        return self._client

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        from google.genai import errors, types

        client = self._get_client()
        config = types.GenerateContentConfig(
            system_instruction=system_prompt, temperature=self._temperature
        )
        try:
            response = client.models.generate_content(
                model=self.model, contents=user_prompt, config=config
            )
        except errors.APIError as exc:
            raise _map_api_error(exc) from exc
        except httpx.TimeoutException as exc:
            raise GenerationTimeoutError("Gemini did not respond in time.") from exc
        except httpx.TransportError as exc:
            logger.warning("Gemini unreachable: %s", exc)
            raise GenerationUnavailableError("The Gemini API is not reachable.") from exc

        answer = (getattr(response, "text", None) or "").strip()
        if not answer:
            raise GenerationUpstreamError("Gemini returned an empty answer.")
        return answer

    def check_readiness(self) -> ProviderStatus:
        # No network call: probing a hosted API from /health could cost money or quota.
        if self._api_key is None:
            return ProviderStatus("not_configured", "GEMINI_API_KEY is not set.")
        return ProviderStatus("configured", "API key present; not probed by the health check.")


def _map_api_error(exc: Any) -> Exception:
    code = getattr(exc, "code", None)
    message = str(getattr(exc, "message", "") or "")
    logger.warning("Gemini API error %s: %s", code, message)
    if code == 429:
        return GenerationRateLimitError("Gemini rate limit or quota reached. Try again later.")
    # Gemini reports an invalid key as HTTP 400 INVALID_ARGUMENT.
    if code in (401, 403) or (code == 400 and "api key" in message.lower()):
        return GenerationConfigError("Gemini rejected the configured API key.")
    if code == 404:
        return GenerationConfigError("The configured GEMINI_MODEL was not found.")
    if code == 400:
        return GenerationUpstreamError("Gemini rejected the request.")
    return GenerationUpstreamError(f"Gemini returned an error (HTTP {code}).")
