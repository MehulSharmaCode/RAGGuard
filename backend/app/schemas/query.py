"""Schemas for question answering."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_TOP_K = 20


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    document_ids: list[UUID] | None = Field(default=None, min_length=1, max_length=100)
    top_k: int | None = Field(default=None, ge=1, le=MAX_TOP_K)

    @field_validator("question")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        return value


class SourceReference(BaseModel):
    """A passage actually retrieved from Qdrant and supplied to the model as evidence."""

    source_id: str = Field(description="Identifier used in the answer text, e.g. 'S1'.")
    document_id: str
    filename: str
    page_number: int | None = Field(description="1-based PDF page; null for TXT files.")
    chunk_index: int
    char_start: int | None = Field(description="Start offset of the excerpt in the page text.")
    char_end: int | None
    excerpt: str
    score: float = Field(description="Cosine similarity between question and passage.")
    cited: bool = Field(description="Whether the generated answer references this source.")


class EvidenceSummary(BaseModel):
    retrieved_count: int
    supporting_count: int
    max_score: float | None
    min_score_threshold: float
    top_k: int


class GenerationInfo(BaseModel):
    provider: str
    model: str
    prompt_version: str


class LatencyBreakdown(BaseModel):
    embedding_ms: float
    retrieval_ms: float
    generation_ms: float | None
    total_ms: float


class QueryResponse(BaseModel):
    answer: str
    status: Literal["answered", "insufficient_evidence"]
    answerable: bool
    fallback_reason: Literal["no_results", "below_threshold", "model_declined"] | None
    sources: list[SourceReference]
    evidence: EvidenceSummary
    generation: GenerationInfo | None = Field(
        description="Null when the LLM was not called (retrieval-stage fallback)."
    )
    latency_ms: LatencyBreakdown
