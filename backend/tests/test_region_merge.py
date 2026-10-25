"""D-072: evidence passages regain the rest of a region that the chunker split into
overlapping windows (heading before, last list items after), within one page."""

from __future__ import annotations

import uuid

from app.core.config import Settings
from app.ingestion.chunking import Chunk
from app.pipeline import RAGPipeline
from app.retrieval.evidence import merge_split_regions
from app.retrieval.vector_store import DocumentRecord, QdrantVectorStore, RetrievedChunk
from app.schemas.query import QueryRequest
from tests.conftest import FakeEmbedder, FakeProvider

PAGE = (
    "Part 6 - Final invention: ORCA\n"  # 0..30
    "Problem. Records arrive from sources of different reliability. "
    "Central mechanism. Three parts: 1. Typed evidence. 2. Graded evaluation. "
    "3. Selective re-evaluation when rules change."
)
# Three overlapping windows of one region, as the structure-aware chunker writes them.
WINDOWS = [(0, 100), (80, 170), (150, len(PAGE))]


def _window(
    index: int, page: int | None = 5, doc: str = "doc", score: float = 0.5
) -> RetrievedChunk:
    start, end = WINDOWS[index]
    return RetrievedChunk(
        f"p{index}", score, doc, "orca.pdf", page, index, PAGE[start:end], start, end
    )


def _neighbours(*chunks: RetrievedChunk) -> dict[tuple[str, int], RetrievedChunk]:
    return {(c.document_id, c.chunk_index): c for c in chunks}


def test_a_window_regains_its_region_heading_and_continuation() -> None:
    (merged,) = merge_split_regions([_window(1)], _neighbours(_window(0), _window(2)))
    assert merged.text == PAGE
    assert (merged.char_start, merged.char_end) == (0, len(PAGE))
    assert (merged.point_id, merged.score, merged.chunk_index) == ("p1", 0.5, 1)


def test_neighbours_that_are_evidence_themselves_are_not_duplicated() -> None:
    first, middle = merge_split_regions(
        [_window(0, score=0.6), _window(1)], _neighbours(_window(0), _window(1), _window(2))
    )
    assert first.text == PAGE[:100]  # its successor is S2 already
    assert middle.text == PAGE[80:]  # gains only the window after it
    assert len([first, middle]) == 2


def test_only_overlapping_windows_on_the_same_page_are_merged() -> None:
    other_page = RetrievedChunk("q", 0.0, "doc", "orca.pdf", 6, 2, PAGE[150:], 150, len(PAGE))
    separate_region = RetrievedChunk("r", 0.0, "doc", "orca.pdf", 5, 0, "Unrelated box.", 0, 14)
    (kept,) = merge_split_regions([_window(1)], _neighbours(separate_region, other_page))
    assert kept == _window(1)


def test_mismatched_overlap_text_is_never_merged() -> None:
    forged = RetrievedChunk("f", 0.0, "doc", "orca.pdf", 5, 2, "X" * 40, 150, 190)
    assert merge_split_regions([_window(1)], _neighbours(forged)) == [_window(1)]


def test_chunks_without_offsets_are_unchanged() -> None:
    bare = RetrievedChunk("b", 0.5, "doc", "a.txt", None, 1, "text", None, None)
    assert merge_split_regions([bare], _neighbours(_window(0))) == [bare]


def _store_windows(store: QdrantVectorStore, embedder: FakeEmbedder, document_id: str) -> None:
    record = DocumentRecord(document_id, "orca.pdf", "pdf", 9, "2026-10-25T10:00:00+00:00", "fake")
    chunks = [
        Chunk(i, 5, PAGE[s:e], s, e, len(PAGE[s:e].split()), units=(PAGE[s:e],))
        for i, (s, e) in enumerate(WINDOWS)
    ]
    vectors = [embedder.embed_documents([c.text, *c.units]) for c in chunks]
    store.upsert_chunks(record, chunks, vectors, embedder.dimension)


def test_store_returns_neighbours_of_the_same_document_only(
    vector_store: QdrantVectorStore, embedder: FakeEmbedder
) -> None:
    mine, other = str(uuid.uuid4()), str(uuid.uuid4())
    _store_windows(vector_store, embedder, mine)
    _store_windows(vector_store, embedder, other)
    probe = RetrievedChunk("x", 0.5, mine, "orca.pdf", 5, 1, PAGE[80:170], 80, 170)
    found = vector_store.neighbours([probe])
    assert sorted(found) == [(mine, 0), (mine, 2)]
    assert found[(mine, 0)].text == PAGE[:100] and found[(mine, 0)].score == 0.0


def test_pipeline_merges_regions_without_changing_scores_or_scope(
    settings: Settings, vector_store: QdrantVectorStore, embedder: FakeEmbedder
) -> None:
    mine, other = str(uuid.uuid4()), str(uuid.uuid4())
    _store_windows(vector_store, embedder, mine)
    _store_windows(vector_store, embedder, other)
    provider = FakeProvider("ORCA has three parts [S1].")
    pipeline = RAGPipeline(settings.model_copy(update={"min_retrieval_score": 0.0}), embedder,
                           vector_store, provider)  # fmt: skip
    request = QueryRequest(question="Central mechanism. Three parts", document_ids=[mine], top_k=1)
    retrieval = pipeline.retrieve_evidence(request)
    (passage,) = retrieval.assessment.supporting
    assert passage.document_id == mine and passage.score == retrieval.retrieved[0].score
    assert passage.text in PAGE and len(passage.text) > len(retrieval.retrieved[0].text)
    response = pipeline.answer(request)
    assert response.sources[0].excerpt == passage.text
    assert {s.document_id for s in response.sources} == {mine}
    assert passage.text in provider.calls[-1][1], "the model receives the merged passage"


def test_extensions_stay_within_the_character_budget() -> None:
    # The passage itself is never shortened; extensions stop when the budget is used up.
    neighbours = _neighbours(_window(0), _window(2))
    window = _window(1)
    (none,) = merge_split_regions([window], neighbours, max_chars=len(window.text))
    assert none == window
    room_for_one = len(window.text) + (WINDOWS[0][1] - WINDOWS[0][0]) - 20
    (one,) = merge_split_regions([window], neighbours, max_chars=room_for_one)
    assert one.text == PAGE[:170]  # the window before fits, the one after does not
