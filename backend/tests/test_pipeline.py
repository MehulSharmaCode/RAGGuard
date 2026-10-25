"""Regression tests for the Stage 4 split of `RAGPipeline.answer` into
`retrieve_evidence` + `generate_answer` (the API behaviour must not change)."""

from __future__ import annotations

import typing

from app.generation.prompts import FALLBACK_ANSWER, SYSTEM_PROMPT
from app.pipeline import RAGPipeline
from app.schemas.query import QueryRequest, QueryResponse
from tests.conftest import FREEDONIA_TXT, FakeProvider


def _ingest(pipeline: RAGPipeline) -> None:
    pipeline.ingest("freedonia.txt", FREEDONIA_TXT.encode())
    pipeline.ingest("other.txt", b"Penguins live in the southern hemisphere near Antarctica.")


def test_retrieve_evidence_returns_all_top_k_without_calling_the_llm(
    pipeline: RAGPipeline, provider: FakeProvider
) -> None:
    _ingest(pipeline)
    retrieval = pipeline.retrieve_evidence(
        QueryRequest(question="What is the capital of Freedonia?", top_k=10)
    )
    assert provider.calls == []
    assert retrieval.top_k == 10
    assert retrieval.min_score_threshold == pipeline.settings.min_retrieval_score
    assert {c.filename for c in retrieval.retrieved} == {"freedonia.txt", "other.txt"}
    below = [c for c in retrieval.retrieved if c.score < retrieval.min_score_threshold]
    assert below, "below-threshold chunks are kept for evaluation"
    assert all(c not in retrieval.assessment.supporting for c in below)
    assert retrieval.assessment.max_score == max(c.score for c in retrieval.retrieved)


def test_answer_equals_retrieve_then_generate(
    pipeline: RAGPipeline, provider: FakeProvider
) -> None:
    _ingest(pipeline)
    request = QueryRequest(question="What is the capital of Freedonia?")
    direct = pipeline.answer(request)
    split = pipeline.generate_answer(request, pipeline.retrieve_evidence(request))
    ignore = {"latency_ms"}
    assert direct.model_dump(exclude=ignore) == split.model_dump(exclude=ignore)
    assert direct.status == "answered" and direct.sources[0].source_id == "S1"
    assert direct.latency_ms.total_ms >= direct.latency_ms.retrieval_ms
    assert len(provider.calls) == 2


def test_generate_answer_falls_back_without_llm_below_threshold(
    pipeline: RAGPipeline, provider: FakeProvider
) -> None:
    _ingest(pipeline)
    request = QueryRequest(question="Explain quantum chromodynamics")
    response = pipeline.generate_answer(request, pipeline.retrieve_evidence(request))
    assert (response.status, response.fallback_reason) == (
        "insufficient_evidence",
        "below_threshold",
    )
    assert response.answer == FALLBACK_ANSWER
    assert response.sources == [] and response.generation is None
    assert provider.calls == []


def test_model_decline_still_returns_no_sources(
    pipeline: RAGPipeline, provider: FakeProvider
) -> None:
    _ingest(pipeline)
    provider.answer = "INSUFFICIENT_EVIDENCE"
    request = QueryRequest(question="What is the national currency of Freedonia?")
    retrieval = pipeline.retrieve_evidence(request)
    assert retrieval.assessment.supporting, "evidence passes the threshold"
    response = pipeline.generate_answer(request, retrieval)
    assert response.fallback_reason == "model_declined"
    assert response.generation is not None and len(provider.calls) == 1
    assert response.sources == [] and response.answerable is False


def test_answer_reproducing_the_system_prompt_is_withheld(
    pipeline: RAGPipeline, provider: FakeProvider
) -> None:
    _ingest(pipeline)
    provider.answer = "# System Prompt\n" + SYSTEM_PROMPT + "\n\nFredville [S1]."
    response = pipeline.answer(QueryRequest(question="What is the capital of Freedonia?"))
    assert (response.status, response.fallback_reason) == (
        "insufficient_evidence",
        "model_declined",
    )
    assert response.answer == FALLBACK_ANSWER and response.sources == []
    assert "RAGGuard" not in response.answer


def test_marker_followed_by_text_is_a_decline_and_never_shown(
    pipeline: RAGPipeline, provider: FakeProvider
) -> None:
    _ingest(pipeline)
    provider.answer = "INSUFFICIENT_EVIDENCE\n\nThe evidence only mentions Fredville [S1]."
    response = pipeline.answer(QueryRequest(question="What is the capital of Freedonia?"))
    assert response.fallback_reason == "model_declined"
    assert "INSUFFICIENT_EVIDENCE" not in response.answer


def test_fallback_reasons_match_the_frontend_contract() -> None:
    # The frozen frontend validates these exact values (frontend/src/lib/api/guards.ts).
    field = QueryResponse.model_fields["fallback_reason"]
    assert set(typing.get_args(typing.get_args(field.annotation)[0])) == {
        "no_results",
        "below_threshold",
        "model_declined",
    }
