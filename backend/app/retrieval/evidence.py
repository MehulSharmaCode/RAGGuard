"""Evidence-sufficiency check that decides whether the LLM is called at all.

Rule: keep retrieved chunks whose score is >= MIN_RETRIEVAL_SCORE (default 0.35 for
the sub-unit index, where a chunk's score is its best sub-unit's cosine, D-063; legacy
single-vector collections use 0.30, D-052; both provisional). If none remain, the
pipeline returns the safe fallback without generation. Similarity alone cannot guarantee that an
answer is correct; the prompt also lets the model decline (see generation).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from app.retrieval.vector_store import RetrievedChunk

FallbackReason = Literal["no_results", "below_threshold", "model_declined"]

# Scores of a legacy single-vector collection are whole-chunk cosines, a different scale
# from the sub-unit index's best-sub-unit cosines (D-063); D-052 calibrated 0.30 for them.
LEGACY_MIN_RETRIEVAL_SCORE = 0.30


def evidence_threshold(configured: float, index_format: str) -> float:
    """The threshold for the index's score scale: the setting, or 0.30 for a legacy index."""
    return LEGACY_MIN_RETRIEVAL_SCORE if index_format == "legacy" else configured


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


def _continues(first: RetrievedChunk, second: RetrievedChunk) -> int:
    """Characters shared by two consecutive windows of one split region, else 0.

    The chunker overlaps chunks only when it windows a region that is longer than one
    chunk (D-063), so an overlap on the same page means "same region, continued". The
    shared text must match exactly; anything else (older indexes, other pages) is 0.
    """
    if (
        first.document_id != second.document_id
        or second.chunk_index != first.chunk_index + 1
        or first.page_number != second.page_number
        or None in (first.char_start, first.char_end, second.char_start, second.char_end)
    ):
        return 0
    assert first.char_start is not None and first.char_end is not None
    assert second.char_start is not None and second.char_end is not None
    shared = first.char_end - second.char_start
    if not (first.char_start < second.char_start and 0 < shared < len(second.text)):
        return 0
    return shared if first.text[-shared:] == second.text[:shared] else 0


# Budget for the text that merging may add (D-072): the evidence of four plain chunks is
# typically under 4,000 characters. Ollama's default context is 4,096 tokens and an
# over-long prompt is truncated from its start (the system rules). Measured with
# qwen3.5:9b: the system prompt is ~930 tokens and a prompt with 6,000 characters of
# evidence ~2,600, leaving room for the answer and for text that tokenizes less well.
MAX_MERGED_EVIDENCE_CHARS = 6000


def merge_split_regions(
    evidence: list[RetrievedChunk],
    neighbours: dict[tuple[str, int], RetrievedChunk],
    max_chars: int = MAX_MERGED_EVIDENCE_CHARS,
) -> list[RetrievedChunk]:
    """Extend each evidence passage with the adjacent windows of its own region (D-072).

    A long region (a section, a numbered list) is split into overlapping windows; the
    best-scoring window alone can lose the region's heading or its last items. Each
    passage gains at most the window before and the window after it, only when they
    continue the same region on the same page and are not evidence themselves. Scores,
    the gate, the number of passages, and their order are unchanged; the merged passage
    is a contiguous span of the page text, so its offsets stay exact. Extensions are
    added in evidence order while the total stays within `max_chars`; the passages
    themselves are never shortened.
    """
    taken = {(c.document_id, c.chunk_index) for c in evidence}
    budget = max_chars - sum(len(c.text) for c in evidence)
    merged: list[RetrievedChunk] = []
    for chunk in evidence:
        text, start, end = chunk.text, chunk.char_start, chunk.char_end
        before = neighbours.get((chunk.document_id, chunk.chunk_index - 1))
        if before is not None and (before.document_id, before.chunk_index) not in taken:
            shared = _continues(before, chunk)
            if shared and len(before.text) - shared <= budget:
                budget -= len(before.text) - shared
                text, start = before.text + text[shared:], before.char_start
                taken.add((before.document_id, before.chunk_index))
        after = neighbours.get((chunk.document_id, chunk.chunk_index + 1))
        if after is not None and (after.document_id, after.chunk_index) not in taken:
            shared = _continues(chunk, after)
            if shared and len(after.text) - shared <= budget:
                budget -= len(after.text) - shared
                text, end = text + after.text[shared:], after.char_end
                taken.add((after.document_id, after.chunk_index))
        merged.append(
            chunk
            if text == chunk.text
            else replace(chunk, text=text, char_start=start, char_end=end)
        )
    return merged
