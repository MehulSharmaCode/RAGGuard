"""Opt-in retrieval diagnostics (D-066): why did a question get evidence or a fallback?

Registered only when RETRIEVAL_DIAGNOSTICS=true (default false), so it is absent from
the API and its OpenAPI schema otherwise. It runs the same retrieval and evidence rule
as POST /query and lists the scored candidates (with short excerpts, the same text that
/query already returns in its sources), which of them become evidence, the size of the
prompt, and, only when asked, the model's raw reply. It stores and logs nothing and
reads only the configured vector store. Intended for a developer on localhost.
"""

from __future__ import annotations

import time

from fastapi import APIRouter

from app.api.dependencies import PipelineDep
from app.generation.prompts import (
    SYSTEM_PROMPT,
    build_user_prompt,
    is_declined,
    leaks_system_prompt,
    source_id,
)
from app.schemas.diagnostics import (
    EXCERPT_CHARS,
    RAW_OUTPUT_CHARS,
    Candidate,
    DiagnosticsRequest,
    DiagnosticsResponse,
    ModelOutput,
)
from app.schemas.query import QueryRequest

router = APIRouter(tags=["diagnostics"])


@router.post("/diagnostics/query", response_model=DiagnosticsResponse)
def diagnose_query(body: DiagnosticsRequest, pipeline: PipelineDep) -> DiagnosticsResponse:
    request = QueryRequest(question=body.question, document_ids=body.document_ids, top_k=body.top_k)
    # Exactly what /query would use as evidence...
    actual = pipeline.retrieve_evidence(request)
    evidence = actual.assessment.supporting
    evidence_ids = {c.point_id: source_id(i) for i, c in enumerate(evidence)}
    # ...and a wider list of candidates for context.
    wide = pipeline.retrieve_evidence(
        QueryRequest(
            question=body.question,
            document_ids=body.document_ids,
            top_k=max(body.candidates, actual.top_k),
        )
    )
    shown = list(evidence) + [c for c in wide.retrieved if c.point_id not in evidence_ids]
    candidates = [
        Candidate(
            rank=rank,
            document_id=c.document_id,
            filename=c.filename,
            page_number=c.page_number,
            chunk_index=c.chunk_index,
            score=round(c.score, 4),
            above_threshold=c.score >= actual.min_score_threshold,
            evidence=c.point_id in evidence_ids,
            source_id=evidence_ids.get(c.point_id),
            excerpt=c.text[:EXCERPT_CHARS],
        )
        for rank, c in enumerate(shown[: body.candidates], start=1)
    ]
    prompt = build_user_prompt(body.question, evidence) if evidence else None
    model: ModelOutput | None = None
    if prompt is not None and body.generate:
        start = time.perf_counter()
        raw = pipeline.provider.generate(SYSTEM_PROMPT, prompt)
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        if leaks_system_prompt(raw):
            model = ModelOutput(interpretation="withheld", raw=None, generation_ms=elapsed)
        else:
            model = ModelOutput(
                interpretation="declined" if is_declined(raw) else "answered",
                raw=raw[:RAW_OUTPUT_CHARS],
                generation_ms=elapsed,
            )
    reason = actual.assessment.fallback_reason
    return DiagnosticsResponse(
        question=body.question,
        index_format=pipeline.vector_store.index_format(),
        threshold=actual.min_score_threshold,
        top_k=actual.top_k,
        decision=reason
        if reason in ("no_results", "below_threshold")
        else ("model_called" if model else "model_not_called"),
        candidates=candidates,
        evidence_count=len(evidence),
        prompt_characters=len(prompt) if prompt else None,
        model=model,
    )
