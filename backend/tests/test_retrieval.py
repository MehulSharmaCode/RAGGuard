"""Embedding vectors, Qdrant storage/retrieval/filtering, and the evidence check."""

from __future__ import annotations

import math
import uuid
from pathlib import Path

import pytest
from qdrant_client import QdrantClient, models

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
    vectors = [[v] for v in embedder.embed_documents([c.text for c in chunks])]
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


def test_hybrid_search_never_leaves_the_document_filter(
    vector_store: QdrantVectorStore, embedder: FakeEmbedder
) -> None:
    # The other document is the stronger semantic and lexical match; neither the lexical
    # candidates nor the closest-below-threshold fill may bring it into a scoped result.
    scoped, other = _record("scoped.pdf"), _record("other.pdf")
    _index(vector_store, embedder, scoped, [(1, "harbour opening hours")])
    _index(vector_store, embedder, other, [(1, "booking boats booking boats 48 hours")])
    question = "booking boats 48 hours"
    for min_score in (-1.0, 0.99):
        results = vector_store.search(
            embedder.embed_query(question),
            4,
            embedder.dimension,
            [scoped.document_id],
            query_text=question,
            min_score=min_score,
        )
        assert results and {r.document_id for r in results} == {scoped.document_id}


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


# --- sub-unit index and legacy collections (D-063) ------------------------------
def test_chunk_score_is_its_best_matching_subunit(
    vector_store: QdrantVectorStore, embedder: FakeEmbedder
) -> None:
    text = "Tier limits table. Starter has fifty gigabytes. Team has two terabytes."
    chunk = Chunk(0, 1, text, 0, len(text), 12, units=("Team has two terabytes",))
    vectors = [embedder.embed_documents([text, "Team has two terabytes"])]
    vector_store.upsert_chunks(_record(), [chunk], vectors, embedder.dimension)

    query = embedder.embed_query("team terabytes")
    [hit] = vector_store.search(query, 3, embedder.dimension)
    whole = sum(a * b for a, b in zip(query, vectors[0][0], strict=True))
    unit = sum(a * b for a, b in zip(query, vectors[0][1], strict=True))
    assert unit > whole
    assert math.isclose(hit.score, unit, rel_tol=1e-4)
    assert hit.text == text  # the whole chunk stays the evidence passage
    assert vector_store.check_health()["index_format"] == "hybrid"
    assert [d.chunk_count for d in vector_store.list_documents()] == [1]


def _legacy_collection(settings: Settings, embedder: FakeEmbedder, points: int) -> None:
    client = QdrantClient(path=str(settings.qdrant_local_path))
    client.create_collection(
        settings.qdrant_collection_name,
        vectors_config=models.VectorParams(
            size=embedder.dimension, distance=models.Distance.COSINE
        ),
    )
    for i in range(points):
        client.upsert(
            settings.qdrant_collection_name,
            points=[
                models.PointStruct(
                    id=point_id_for("old-doc", i),
                    vector=embedder.embed_documents(["old penguin notes"])[0],
                    payload={
                        "document_id": "old-doc",
                        "filename": "old.txt",
                        "file_type": "txt",
                        "total_pages": None,
                        "ingested_at": "2026-10-01T00:00:00+00:00",
                        "page_number": None,
                        "chunk_index": i,
                        "text": "old penguin notes",
                        "char_start": 0,
                        "char_end": 17,
                    },
                )
            ],
        )
    client.close()


def test_legacy_collection_keeps_documents_and_stays_searchable(
    settings: Settings, embedder: FakeEmbedder
) -> None:
    _legacy_collection(settings, embedder, points=1)
    store = QdrantVectorStore.from_settings(settings)
    try:
        assert store.check_health()["index_format"] == "legacy"
        assert store.search(embedder.embed_query("penguin"), 3, embedder.dimension)[0].text == (
            "old penguin notes"
        )
        new = Chunk(0, None, "new walrus notes", 0, 16, 3, units=("walrus notes here",))
        vectors = [embedder.embed_documents(["new walrus notes", "walrus notes here"])]
        store.upsert_chunks(_record("new.txt", "txt"), [new], vectors, embedder.dimension)
        assert store.check_health() == {
            "collection_exists": True, "points": 2, "index_format": "legacy"
        }  # fmt: skip
        assert {d.filename for d in store.list_documents()} == {"old.txt", "new.txt"}
    finally:
        store.close()


def test_empty_legacy_collection_is_recreated_as_hybrid_index(
    settings: Settings, embedder: FakeEmbedder
) -> None:
    _legacy_collection(settings, embedder, points=0)
    store = QdrantVectorStore.from_settings(settings)
    try:
        assert store.check_health()["index_format"] == "legacy"
        _index(store, embedder, _record(), [(1, "penguins are birds")])
        assert store.check_health()["index_format"] == "hybrid"
    finally:
        store.close()


# --- evidence check --------------------------------------------------------------
# --- hybrid index (D-064) ----------------------------------------------------------
def test_lexical_ranking_promotes_exact_terms_but_scores_stay_dense(
    vector_store: QdrantVectorStore, embedder: FakeEmbedder
) -> None:
    texts = [(1, f"filler topic number {i} about harbours and ships") for i in range(8)]
    texts.append((2, "harbours ships summary; application state machine DRAFT READY_TO_SUBMIT"))
    _index(vector_store, embedder, _record(), texts)
    question = "harbours ships application state machine"
    query = embedder.embed_query(question)
    dense_only = vector_store.search(query, 2, embedder.dimension)
    hybrid = vector_store.search(query, 2, embedder.dimension, query_text=question, min_score=-1.0)
    assert any("state machine" in c.text for c in hybrid)
    for chunk in hybrid + dense_only:  # the reported score is always the dense cosine
        assert -1.0 <= chunk.score <= 1.0 + 1e-6
    by_text = {c.text: c.score for c in dense_only + hybrid}
    assert len(by_text) == len({c.text for c in dense_only + hybrid})


def test_hybrid_search_prefers_chunks_above_the_gate(
    vector_store: QdrantVectorStore, embedder: FakeEmbedder
) -> None:
    _index(
        vector_store,
        embedder,
        _record(),
        [(1, "penguins swim in cold water"), (1, "volcano lava eruption penguins"), (2, "weather")],
    )
    question = "penguins swim cold water"
    query = embedder.embed_query(question)
    results = vector_store.search(query, 2, embedder.dimension, query_text=question, min_score=0.5)
    assert results[0].text == "penguins swim in cold water"
    assert results[0].score >= 0.5
    assert all(r.score < 0.5 for r in results[1:])  # below-gate chunks only fill up the list


def test_hybrid_evidence_is_presented_in_dense_score_order(
    vector_store: QdrantVectorStore, embedder: FakeEmbedder
) -> None:
    texts = [(1, f"harbour ships filler topic {i}") for i in range(6)]
    texts.append((1, "harbour ships booking procedure booking booking"))
    _index(vector_store, embedder, _record(), texts)
    question = "harbour ships booking"
    results = vector_store.search(
        embedder.embed_query(question), 4, embedder.dimension, query_text=question, min_score=-1.0
    )
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_subunit_collection_from_d063_keeps_working(
    settings: Settings, embedder: FakeEmbedder
) -> None:
    client = QdrantClient(path=str(settings.qdrant_local_path))
    client.create_collection(
        settings.qdrant_collection_name,
        vectors_config=models.VectorParams(
            size=embedder.dimension,
            distance=models.Distance.COSINE,
            multivector_config=models.MultiVectorConfig(
                comparator=models.MultiVectorComparator.MAX_SIM
            ),
        ),
    )
    client.upsert(
        settings.qdrant_collection_name,
        points=[
            models.PointStruct(
                id=point_id_for("old-doc", 0),
                vector=embedder.embed_documents(["walrus notes"]),
                payload={
                    "document_id": "old-doc",
                    "filename": "old.txt",
                    "chunk_index": 0,
                    "text": "walrus notes",
                    "ingested_at": "2026-10-16T00:00:00+00:00",
                },
            )
        ],
    )
    client.close()
    store = QdrantVectorStore.from_settings(settings)
    try:
        _index(store, embedder, _record(), [(1, "penguins are birds")])
        assert store.check_health()["index_format"] == "subunit"
        assert {d.filename for d in store.list_documents()} == {"old.txt", "doc.pdf"}
        hits = store.search(
            embedder.embed_query("penguins"), 3, embedder.dimension, query_text="penguins"
        )
        assert hits[0].text == "penguins are birds"
    finally:
        store.close()


def test_lexical_helpers() -> None:
    from app.retrieval.lexical import (
        document_vector,
        query_vector,
        reciprocal_rank_fusion,
        tokens,
    )

    assert tokens("What is the READY_TO_SUBMIT state?") == ["ready_to_submit", "state"]
    indices, values = document_vector("state state machine")
    assert len(indices) == 2 and all(v > 0 for v in values)
    assert query_vector("the a of")[0] == []  # stopwords only: no lexical query
    assert reciprocal_rank_fusion(["a", "b"], ["b", "c"])[0] == "b"


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
