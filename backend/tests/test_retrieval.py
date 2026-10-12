"""Embedding vectors, Qdrant storage/retrieval/filtering, and the evidence check."""

from __future__ import annotations

import math
import uuid
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.errors import ConfigurationError, VectorStoreError
from app.ingestion.chunking import Chunk
from app.retrieval.evidence import assess_evidence
from app.retrieval.vector_store import (
    DocumentRecord,
    QdrantVectorStore,
    RetrievedChunk,
    point_id_for,
)
from tests.conftest import FakeEmbedder


def _record(filename: str = "doc.pdf", file_type: str = "pdf") -> DocumentRecord:
    return DocumentRecord(
        document_id=str(uuid.uuid4()),
        filename=filename,
        file_type=file_type,
        total_pages=2,
        ingested_at="2026-10-12T10:00:00+00:00",
        embedding_model="fake-hash-embedder",
    )


def _chunks(texts: list[tuple[int | None, str]]) -> list[Chunk]:
    return [
        Chunk(
            chunk_index=i,
            page_number=page,
            text=text,
            char_start=0,
            char_end=len(text),
            token_count=len(text.split()),
        )
        for i, (page, text) in enumerate(texts)
    ]


def _index(
    store: QdrantVectorStore,
    embedder: FakeEmbedder,
    record: DocumentRecord,
    texts: list[tuple[int | None, str]],
) -> list[Chunk]:
    chunks = _chunks(texts)
    vectors = embedder.embed_documents([c.text for c in chunks])
    store.upsert_chunks(record, chunks, vectors, embedder.dimension)
    return chunks


# --- embeddings (fake) -----------------------------------------------------------
def test_fake_embeddings_are_normalized_with_expected_dimension(embedder: FakeEmbedder) -> None:
    vectors = embedder.embed_documents(["alpha beta", "gamma"])
    assert all(len(v) == embedder.dimension for v in vectors)
    assert all(math.isclose(sum(x * x for x in v), 1.0) for v in vectors)


# --- storage and payloads --------------------------------------------------------
def test_upsert_stores_complete_payload_and_unique_ids(
    vector_store: QdrantVectorStore, embedder: FakeEmbedder
) -> None:
    record = _record()
    _index(vector_store, embedder, record, [(1, "violins exported widely"), (2, "river city")])

    results = vector_store.search(embedder.embed_query("violins"), 5, embedder.dimension)
    top = results[0]
    assert isinstance(top, RetrievedChunk)
    assert top.document_id == record.document_id
    assert top.filename == "doc.pdf"
    assert top.page_number == 1
    assert top.chunk_index == 0
    assert top.text == "violins exported widely"
    assert top.char_start == 0 and top.char_end == len(top.text)
    assert top.point_id == point_id_for(record.document_id, 0)
    assert len({r.point_id for r in results}) == len(results) == 2


def test_point_ids_are_deterministic_and_document_scoped() -> None:
    assert point_id_for("doc-a", 0) == point_id_for("doc-a", 0)
    assert point_id_for("doc-a", 0) != point_id_for("doc-a", 1)
    assert point_id_for("doc-a", 0) != point_id_for("doc-b", 0)


def test_second_upload_does_not_overwrite_first(
    vector_store: QdrantVectorStore, embedder: FakeEmbedder
) -> None:
    first, second = _record("a.txt", "txt"), _record("a.txt", "txt")
    _index(vector_store, embedder, first, [(None, "same text")])
    _index(vector_store, embedder, second, [(None, "same text")])
    documents = vector_store.list_documents()
    assert {d.document_id for d in documents} == {first.document_id, second.document_id}


def test_search_orders_by_cosine_score_and_respects_top_k(
    vector_store: QdrantVectorStore, embedder: FakeEmbedder
) -> None:
    _index(
        vector_store,
        embedder,
        _record(),
        [
            (1, "penguins swim in cold antarctic water"),
            (1, "penguins are birds"),
            (2, "volcanoes erupt lava"),
        ],
    )
    results = vector_store.search(
        embedder.embed_query("penguins swim cold water"), 2, embedder.dimension
    )
    assert len(results) == 2
    assert results[0].text.startswith("penguins swim")
    assert results[0].score >= results[1].score
    assert -1.0 <= results[1].score <= 1.0 + 1e-6


def test_search_filters_by_document_ids(
    vector_store: QdrantVectorStore, embedder: FakeEmbedder
) -> None:
    doc_a, doc_b = _record("a.pdf"), _record("b.pdf")
    _index(vector_store, embedder, doc_a, [(1, "shared topic alpha")])
    _index(vector_store, embedder, doc_b, [(1, "shared topic beta")])

    query = embedder.embed_query("shared topic")
    only_b = vector_store.search(query, 5, embedder.dimension, [doc_b.document_id])
    assert [r.document_id for r in only_b] == [doc_b.document_id]
    both = vector_store.search(query, 5, embedder.dimension)
    assert {r.document_id for r in both} == {doc_a.document_id, doc_b.document_id}


def test_search_before_any_ingest_returns_empty(
    vector_store: QdrantVectorStore, embedder: FakeEmbedder
) -> None:
    assert vector_store.search(embedder.embed_query("x"), 4, embedder.dimension) == []
    assert vector_store.list_documents() == []


def test_list_and_delete_documents(vector_store: QdrantVectorStore, embedder: FakeEmbedder) -> None:
    keep, remove = _record("keep.pdf"), _record("remove.pdf")
    _index(vector_store, embedder, keep, [(1, "one"), (2, "two")])
    _index(vector_store, embedder, remove, [(1, "three")])

    summaries = {d.document_id: d for d in vector_store.list_documents()}
    assert summaries[keep.document_id].chunk_count == 2
    assert summaries[keep.document_id].filename == "keep.pdf"

    assert vector_store.delete_document(remove.document_id) == 1
    assert [d.document_id for d in vector_store.list_documents()] == [keep.document_id]
    assert vector_store.delete_document(remove.document_id) == 0


def test_dimension_mismatch_is_reported_as_configuration_error(
    vector_store: QdrantVectorStore, embedder: FakeEmbedder
) -> None:
    _index(vector_store, embedder, _record(), [(1, "text")])
    other = FakeEmbedder(dimension=128)
    # Fresh store instance on the same collection, as after a model change + restart.
    vector_store.close()
    with pytest.raises(ConfigurationError, match="128"):
        vector_store.search(other.embed_query("text"), 4, other.dimension)


def test_vector_length_is_validated(
    vector_store: QdrantVectorStore, embedder: FakeEmbedder
) -> None:
    with pytest.raises(ConfigurationError):
        vector_store.search([0.1, 0.2], 4, embedder.dimension)


def test_unavailable_storage_raises_vector_store_error() -> None:
    def broken_factory():  # type: ignore[no-untyped-def]
        raise ConnectionError("connection refused")

    store = QdrantVectorStore(broken_factory, "c", is_local=False)
    with pytest.raises(VectorStoreError) as info:
        store.list_documents()
    assert "refused" not in info.value.message  # internal details are not exposed


def test_local_and_remote_modes_are_exclusive(tmp_path: Path) -> None:
    local = Settings(_env_file=None, qdrant_url="", qdrant_local_path=tmp_path)  # type: ignore[call-arg]
    remote = Settings(_env_file=None, qdrant_url="http://qdrant:6333")  # type: ignore[call-arg]
    assert local.qdrant_url is None
    assert QdrantVectorStore.from_settings(local).is_local is True
    assert QdrantVectorStore.from_settings(remote).is_local is False


# --- evidence check --------------------------------------------------------------
def _hit(score: float) -> RetrievedChunk:
    return RetrievedChunk("p", score, "d", "f.txt", None, 0, "t", 0, 1)


def test_evidence_no_results() -> None:
    assessment = assess_evidence([], 0.3)
    assert not assessment.sufficient
    assert assessment.fallback_reason == "no_results"
    assert assessment.max_score is None


def test_evidence_all_below_threshold() -> None:
    assessment = assess_evidence([_hit(0.2), _hit(0.1)], 0.3)
    assert assessment.fallback_reason == "below_threshold"
    assert assessment.supporting == []
    assert assessment.max_score == 0.2


def test_evidence_keeps_only_chunks_at_or_above_threshold() -> None:
    assessment = assess_evidence([_hit(0.8), _hit(0.3), _hit(0.29)], 0.3)
    assert assessment.sufficient
    assert [c.score for c in assessment.supporting] == [0.8, 0.3]
