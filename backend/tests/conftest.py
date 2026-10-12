"""Shared fixtures and fakes.

Tests never call Gemini, never need a running Ollama service, and never touch the
development Qdrant database: each test gets its own temporary Qdrant directory
and a uniquely named collection.
"""

from __future__ import annotations

import hashlib
import math
import re
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.generation.base import ProviderStatus
from app.main import create_app
from app.pipeline import RAGPipeline
from app.retrieval.vector_store import QdrantVectorStore

_WORD = re.compile(r"\w+|[^\w\s]")
_STOPWORDS = {
    "a", "an", "the", "of", "is", "are", "was", "what", "which", "who", "how", "in", "on",
    "to", "and", "or", "does", "do", "for", "by", "with", "at", "it", "its", "that", "this",
}  # fmt: skip


class FakeEmbedder:
    """Deterministic hashed bag-of-words embedder: shared content words => high cosine."""

    model_name = "fake-hash-embedder"

    def __init__(self, dimension: int = 256, max_input_tokens: int = 254) -> None:
        self._dimension = dimension
        self._max_input_tokens = max_input_tokens
        self.calls = 0

    @property
    def is_loaded(self) -> bool:
        return True

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def max_input_tokens(self) -> int:
        return self._max_input_tokens

    def token_spans(self, text: str) -> list[tuple[int, int]]:
        return [m.span() for m in _WORD.finditer(text)]

    def _embed(self, text: str) -> list[float]:
        self.calls += 1
        vector = [0.0] * self._dimension
        for word in re.findall(r"\w+", text.lower()):
            if word in _STOPWORDS:
                continue
            digest = hashlib.sha256(word.encode()).digest()
            vector[int.from_bytes(digest[:4], "big") % self._dimension] += 1.0
        norm = math.sqrt(sum(x * x for x in vector))
        return [x / norm for x in vector] if norm else vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class FakeProvider:
    """Records prompts and returns a canned answer (or raises a configured error)."""

    name = "fake"
    model = "fake-model"

    def __init__(
        self,
        answer: str = "Fredville is the capital of Freedonia [S1].",
        error: Exception | None = None,
        status: ProviderStatus | None = None,
    ) -> None:
        self.answer = answer
        self.error = error
        self.status = status or ProviderStatus("ready", "fake provider")
        self.calls: list[tuple[str, str]] = []

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.calls.append((system_prompt, user_prompt))
        if self.error is not None:
            raise self.error
        return self.answer

    def check_readiness(self) -> ProviderStatus:
        return self.status


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[str]) -> bytes:
    """Build a minimal valid PDF with one text page per entry ('' gives a blank page)."""
    page_ids = [4 + 2 * i for i in range(len(pages))]
    objects: dict[int, str] = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] "
        f"/Count {len(pages)} >>",
        3: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for page_id, text in zip(page_ids, pages, strict=True):
        lines = " ".join(f"({_pdf_escape(line)}) Tj T*" for line in text.split("\n") if line)
        stream = f"BT /F1 12 Tf 72 720 Td 14 TL {lines} ET"
        objects[page_id] = (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_id + 1} 0 R >>"
        )
        objects[page_id + 1] = f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n{objects[number]}\nendobj\n".encode("latin-1")
    xref_at = len(out)
    size = max(objects) + 1
    out += f"xref\n0 {size}\n0000000000 65535 f \n".encode()
    for number in range(1, size):
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]  # never read the developer's .env
        generation_provider="ollama",
        qdrant_url=None,
        qdrant_local_path=tmp_path / "qdrant",
        qdrant_collection_name=f"test_{uuid.uuid4().hex[:12]}",
        chunk_size_tokens=40,
        chunk_overlap_tokens=8,
        default_top_k=4,
        max_upload_size_mb=1,
        min_retrieval_score=0.3,
    )


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def vector_store(settings: Settings) -> Iterator[QdrantVectorStore]:
    store = QdrantVectorStore.from_settings(settings)
    yield store
    store.close()


@pytest.fixture
def pipeline(
    settings: Settings,
    embedder: FakeEmbedder,
    vector_store: QdrantVectorStore,
    provider: FakeProvider,
) -> RAGPipeline:
    return RAGPipeline(settings, embedder, vector_store, provider)


@pytest.fixture
def client(settings: Settings, pipeline: RAGPipeline) -> Iterator[TestClient]:
    with TestClient(create_app(settings, pipeline)) as test_client:
        yield test_client


FREEDONIA_TXT = (
    "Freedonia is a small fictional country. The capital of Freedonia is Fredville, "
    "a river city founded in 1820.\n\n"
    "The national currency of Freedonia is the Freedonian crown. "
    "Its main export is hand-made violins."
)

ORBIT_PAGES = [
    "Orbital mechanics overview. Satellites in low Earth orbit circle the planet "
    "roughly every ninety minutes.",
    "",
    "Geostationary satellites orbit at about 35786 kilometres altitude and match "
    "the rotation period of the Earth.",
]
