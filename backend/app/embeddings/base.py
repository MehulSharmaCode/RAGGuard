"""Embedding interface shared by indexing and querying."""

from __future__ import annotations

from typing import Protocol


class Embedder(Protocol):
    """Produces L2-normalized vectors; also exposes its tokenizer for chunking."""

    model_name: str

    @property
    def is_loaded(self) -> bool: ...

    @property
    def dimension(self) -> int: ...

    @property
    def max_input_tokens(self) -> int:
        """Content tokens the model accepts per input, excluding special tokens."""
        ...

    def token_spans(self, text: str) -> list[tuple[int, int]]: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...
