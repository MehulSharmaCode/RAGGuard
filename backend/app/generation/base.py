"""LLM provider interface. Providers only turn prompts into text; retrieval,
prompt construction, and source references live outside them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

ProviderState = Literal["ready", "unavailable", "model_missing", "not_configured", "configured"]


@dataclass(frozen=True)
class ProviderStatus:
    """Readiness without making a generation call.

    "configured" means credentials are present but readiness was not probed,
    because probing a hosted provider would cost a network call.
    """

    state: ProviderState
    detail: str

    @property
    def ready(self) -> bool:
        return self.state in ("ready", "configured")


class GenerationProvider(Protocol):
    name: str
    model: str

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Return the final answer text. Raises a Generation*Error on failure."""
        ...

    def check_readiness(self) -> ProviderStatus: ...
