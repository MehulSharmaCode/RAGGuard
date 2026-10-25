"""Response models of the opt-in retrieval diagnostics endpoint (D-066)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.query import QueryRequest

EXCERPT_CHARS = 400
RAW_OUTPUT_CHARS = 2000


class DiagnosticsRequest(QueryRequest):
    """A /query request plus how many candidates to show and whether to call the model."""

    candidates: int = Field(default=10, ge=1, le=30, description="Candidates to list.")
    generate: bool = Field(
        default=False,
        description="Also call the model on the evidence and return its raw reply.",
    )


class Candidate(BaseModel):
    rank: int = Field(description="1-based position in the retrieval order (hybrid: fused).")
    document_id: str
    filename: str
    page_number: int | None
    chunk_index: int
    score: float = Field(description="Dense score (best sub-unit cosine) used by the gate.")
    above_threshold: bool
    evidence: bool = Field(description="Sent to the model as evidence by POST /query.")
    source_id: str | None = Field(description="S1.. label when the chunk is evidence.")
    excerpt: str = Field(description=f"First {EXCERPT_CHARS} characters of the chunk.")


class ModelOutput(BaseModel):
    interpretation: Literal["answered", "declined", "withheld"]
    raw: str | None = Field(
        description=f"The model's reply (first {RAW_OUTPUT_CHARS} characters); withheld when "
        "it reproduces the system prompt."
    )
    generation_ms: float


class DiagnosticsResponse(BaseModel):
    question: str
    index_format: str
    threshold: float
    top_k: int
    decision: Literal["no_results", "below_threshold", "model_called", "model_not_called"]
    candidates: list[Candidate]
    evidence_count: int
    prompt_characters: int | None = Field(
        description="Size of the user prompt that /query would send (null without evidence)."
    )
    model: ModelOutput | None
