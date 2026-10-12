"""Token-aware overlapping chunking.

Chunks are windows of `chunk_size` tokens that advance by `chunk_size - overlap`
tokens, measured with the embedding model's own tokenizer so every chunk fits
the model's input limit. Chunks never cross a PDF page boundary, which keeps page
citations exact. Each chunk records its character span in the page text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.ingestion.extraction import PageText


class Tokenizer(Protocol):
    def token_spans(self, text: str) -> list[tuple[int, int]]:
        """Return (start, end) character offsets of each token, without special tokens."""
        ...


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    page_number: int | None
    text: str
    char_start: int
    char_end: int
    token_count: int


def chunk_pages(
    pages: list[PageText], tokenizer: Tokenizer, chunk_size: int, overlap: int
) -> list[Chunk]:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not 0 <= overlap < chunk_size:
        raise ValueError("overlap must be >= 0 and smaller than chunk_size")

    step = chunk_size - overlap
    chunks: list[Chunk] = []
    for page in pages:
        spans = [(s, e) for s, e in tokenizer.token_spans(page.text) if e > s]
        start = 0
        while start < len(spans):
            window = spans[start : start + chunk_size]
            char_start, char_end = window[0][0], window[-1][1]
            text = page.text[char_start:char_end].strip()
            if text:
                chunks.append(
                    Chunk(
                        chunk_index=len(chunks),
                        page_number=page.page_number,
                        text=text,
                        char_start=char_start,
                        char_end=char_end,
                        token_count=len(window),
                    )
                )
            if start + chunk_size >= len(spans):
                break
            start += step
    return chunks
