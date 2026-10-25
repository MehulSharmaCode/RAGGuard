"""Offline sweep of the retrieval evidence threshold (`MIN_RETRIEVAL_SCORE`).

Computed from recorded scores only: no query is re-run and no answer regenerated.
For each candidate threshold t, the retrieval gate predicts "answerable" when the
case's highest retrieved cosine score is >= t (the pipeline's evidence rule).

The sweep estimates retrieval-based answerability classification; it says nothing
about whether an answer is correct.
"""

from __future__ import annotations

import statistics
from collections import defaultdict

from app.evaluation.metrics import classification_scores, rate
from app.evaluation.schemas import (
    CaseResult,
    ClassificationScores,
    HighSimilarityFailure,
    ScoreDistribution,
    ThresholdAnalysis,
    ThresholdCase,
    ThresholdPoint,
)

DEFAULT_CANDIDATES: tuple[float, ...] = tuple(round(i * 0.05, 2) for i in range(19))  # 0.00-0.90

NOTES = [
    "Retrieval-gate scores: a case is predicted answerable when its highest retrieved cosine "
    "similarity is >= the threshold. Positive class = answerable.",
    "Scores are Qdrant COSINE similarities of normalized embeddings (all-MiniLM-L6-v2 by "
    "default) in [-1, 1], the same values the pipeline compares with MIN_RETRIEVAL_SCORE.",
    "estimated_end_to_end combines the gate with the model decision recorded in this run "
    "(answer or decline). It is only given for thresholds >= the run threshold, because below "
    "it the model never saw the extra cases. It assumes the model would decide the same way "
    "with fewer evidence passages, which is not guaranteed.",
    "The sweep estimates answerability classification only; it does not measure answer "
    "correctness. With a small dataset, a single case moves every rate noticeably.",
]


def _scores(answerable: list[bool], predicted: list[bool]) -> ClassificationScores:
    tp = sum(a and p for a, p in zip(answerable, predicted, strict=True))
    fp = sum(not a and p for a, p in zip(answerable, predicted, strict=True))
    tn = sum(not a and not p for a, p in zip(answerable, predicted, strict=True))
    fn = sum(a and not p for a, p in zip(answerable, predicted, strict=True))
    return classification_scores(tp, fp, tn, fn)


def _distribution(values: list[float]) -> ScoreDistribution:
    if not values:
        return ScoreDistribution(count=0, min=None, median=None, max=None)
    return ScoreDistribution(
        count=len(values),
        min=round(min(values), 4),
        median=round(statistics.median(values), 4),
        max=round(max(values), 4),
    )


def _high_similarity_failures(
    scored: list[CaseResult], run_threshold: float
) -> list[HighSimilarityFailure]:
    failures: list[HighSimilarityFailure] = []
    for r in scored:
        assert r.max_score is not None
        if r.max_score < run_threshold or r.outcome == "error":
            continue
        problem: str | None = None
        if r.answerability == "unanswerable" and r.outcome == "answered":
            problem = "Unanswerable question answered (false answer)."
        elif r.answerability == "answerable" and r.outcome == "fallback":
            problem = f"Answerable question refused ({r.fallback_reason})."
        elif (
            r.answerability == "answerable"
            and r.facts
            and r.facts.facts_found < r.facts.facts_total
        ):
            problem = "Answered, but required facts are missing: " + ", ".join(r.facts.missing)
        elif r.retrieval is not None and r.retrieval.hit_at_k is False:
            problem = "No expected source among the retrieved passages."
        if problem:
            failures.append(
                HighSimilarityFailure(
                    case_id=r.case_id,
                    category=r.category,
                    max_score=r.max_score,
                    outcome=r.outcome,
                    problem=problem,
                )
            )
    return sorted(failures, key=lambda f: -f.max_score)


def analyse_thresholds(
    results: list[CaseResult],
    run_threshold: float,
    candidates: tuple[float, ...] = DEFAULT_CANDIDATES,
) -> ThresholdAnalysis:
    grid = sorted({round(c, 4) for c in (*candidates, run_threshold)})
    scored = [r for r in results if r.max_score is not None]
    answerable = [r.answerability == "answerable" for r in scored]
    max_scores = [r.max_score for r in scored if r.max_score is not None]
    # Model decision as recorded: only meaningful for cases that passed the run threshold.
    decided = [r for r in scored if r.outcome != "error"]

    by_category: dict[str, list[CaseResult]] = defaultdict(list)
    for r in scored:
        by_category[r.category].append(r)

    points: list[ThresholdPoint] = []
    for t in grid:
        predicted = [s >= t for s in max_scores]
        end_to_end = None
        if t >= run_threshold:
            end_to_end = _scores(
                [r.answerability == "answerable" for r in decided],
                [
                    r.max_score is not None and r.max_score >= t and r.outcome == "answered"
                    for r in decided
                ],
            )
        points.append(
            ThresholdPoint(
                threshold=t,
                **_scores(answerable, predicted).model_dump(),
                pass_rate_by_category={
                    category: rate(sum(1 for r in rs if (r.max_score or 0) >= t), len(rs))
                    for category, rs in sorted(by_category.items())
                },
                estimated_end_to_end=end_to_end,
            )
        )

    f1_values = [p.f1.value for p in points if p.f1.value is not None]
    best_f1 = max(f1_values) if f1_values else None
    answerable_scores = [
        r.max_score for r in scored if r.answerability == "answerable" and r.max_score is not None
    ]
    unanswerable_scores = [
        r.max_score for r in scored if r.answerability == "unanswerable" and r.max_score is not None
    ]
    low = min(answerable_scores) if answerable_scores else None
    high = max(unanswerable_scores) if unanswerable_scores else None
    overlapping: list[str] = []
    if low is not None and high is not None and high >= low:
        overlapping = [
            r.case_id for r in scored if r.max_score is not None and low <= r.max_score <= high
        ]

    groups: dict[str, list[float]] = defaultdict(list)
    for r in scored:
        assert r.max_score is not None
        groups[r.category].append(r.max_score)
        groups[f"all_{r.answerability}"].append(r.max_score)

    return ThresholdAnalysis(
        run_threshold=run_threshold,
        candidates=grid,
        points=points,
        selected=next(p for p in points if p.threshold == round(run_threshold, 4)),
        best_retrieval_f1_thresholds=[
            p.threshold for p in points if best_f1 is not None and p.f1.value == best_f1
        ],
        score_distribution={k: _distribution(v) for k, v in sorted(groups.items())},
        lowest_answerable_max_score=None if low is None else round(low, 4),
        highest_unanswerable_max_score=None if high is None else round(high, 4),
        overlapping_cases=overlapping,
        high_similarity_failures=_high_similarity_failures(scored, run_threshold),
        excluded_cases=[r.case_id for r in results if r.max_score is None],
        per_case=[
            ThresholdCase(
                case_id=r.case_id,
                category=r.category,
                answerability=r.answerability,
                max_score=r.max_score,
                passes_run_threshold=None if r.max_score is None else r.max_score >= run_threshold,
                outcome=r.outcome,
                classification=r.classification,
            )
            for r in results
        ],
        notes=NOTES,
    )
