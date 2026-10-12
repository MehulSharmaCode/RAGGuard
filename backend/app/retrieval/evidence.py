"""Evidence-sufficiency check that decides whether the LLM is called at all.

Rule (provisional, tuned in Stage 4): keep retrieved chunks whose cosine
similarity is >= MIN_RETRIEVAL_SCORE. If none remain, the pipeline returns the
safe fallback without generation. Similarity alone cannot guarantee that an
answer is correct; the prompt also lets the model decline (see generation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.retrieval.vector_store import RetrievedChunk

FallbackReason = Literal["no_results", "below_threshold", "model_declined"]


@dataclass(frozen=True)
class EvidenceAssessment:
    supporting: list[RetrievedChunk]
    max_score: float | None
    fallback_reason: FallbackReason | None

    @property
    def sufficient(self) -> bool:
        return self.fallback_reason is None


def assess_evidence(retrieved: list[RetrievedChunk], min_score: float) -> EvidenceAssessment:
    if not retrieved:
        return EvidenceAssessment(supporting=[], max_score=None, fallback_reason="no_results")
    max_score = max(c.score for c in retrieved)
    supporting = [c for c in retrieved if c.score >= min_score]
    return EvidenceAssessment(
        supporting=supporting,
        max_score=max_score,
        fallback_reason=None if supporting else "below_threshold",
    )
