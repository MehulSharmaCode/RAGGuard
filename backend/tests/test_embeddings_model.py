"""Checks against the real Sentence Transformers model.

These run only if the model is already in the local Hugging Face cache (they
never download it) and are skipped otherwise, with the reason reported.
"""

from __future__ import annotations

import math

import pytest

from app.embeddings.sentence_transformer import SentenceTransformerEmbedder
from app.ingestion.chunking import chunk_pages
from app.ingestion.extraction import PageText

MODEL = "sentence-transformers/all-MiniLM-L6-v2"


@pytest.fixture(scope="module")
def real_embedder() -> SentenceTransformerEmbedder:
    embedder = SentenceTransformerEmbedder(MODEL, local_files_only=True)
    try:
        _ = embedder.dimension
    except Exception:
        pytest.skip(f"{MODEL} is not in the local Hugging Face cache")
    return embedder


def test_real_model_dimension_and_normalization(real_embedder: SentenceTransformerEmbedder) -> None:
    assert real_embedder.dimension == 384
    vectors = real_embedder.embed_documents(["Fredville is the capital.", "Violins."])
    assert [len(v) for v in vectors] == [384, 384]
    assert all(math.isclose(sum(x * x for x in v), 1.0, rel_tol=1e-4) for v in vectors)
    assert len(real_embedder.embed_query("capital?")) == 384


def test_real_model_input_limit_fits_default_chunk_size(
    real_embedder: SentenceTransformerEmbedder,
) -> None:
    assert real_embedder.max_input_tokens >= 180


def test_real_tokenizer_chunks_stay_within_limit(
    real_embedder: SentenceTransformerEmbedder,
) -> None:
    text = " ".join(f"Sentence number {i} discusses tokenization." for i in range(200))
    chunks = chunk_pages([PageText(None, text)], real_embedder, chunk_size=180, overlap=30)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.token_count <= 180
        assert text[chunk.char_start : chunk.char_end].strip() == chunk.text
        assert len(real_embedder.token_spans(chunk.text)) <= real_embedder.max_input_tokens
