"""Principal metrics shown by the Evaluation and Experiments views.

Each key is a JSON path inside a report's `aggregates`, which is also the MLflow metric
name logged for it (`app/tracking/mlflow_tracking.py`), so one catalog serves saved
reports and tracked runs. `direction` says which way is better; it drives the
improved/regressed labels of the run comparison and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

MetricKind = Literal["rate", "mean", "count", "ms"]
Direction = Literal["higher", "lower", "neutral"]

GROUPS = (
    "Answers",
    "Retrieval and citations",
    "Security",
    "Latency",
    "LLM judge (supplementary)",
)


@dataclass(frozen=True)
class CatalogMetric:
    key: str
    label: str
    group: str
    direction: Direction
    kind: MetricKind
    supplementary: bool = False


def _m(
    key: str, label: str, group: str, direction: Direction, kind: MetricKind = "rate"
) -> CatalogMetric:
    return CatalogMetric(key, label, group, direction, kind, group == GROUPS[4])


CATALOG: tuple[CatalogMetric, ...] = (
    _m("correctness.case_pass_rate", "Case pass rate", GROUPS[0], "higher"),
    _m(
        "correctness.answer_correct_rate",
        "Correct answers (answerable cases)",
        GROUPS[0],
        "higher",
    ),
    _m(
        "answerability.correct_fallback_rate",
        "Correct abstentions (unanswerable cases)",
        GROUPS[0],
        "higher",
    ),
    _m(
        "answerability.false_answer_rate",
        "False answers (unanswerable cases)",
        GROUPS[0],
        "lower",
    ),
    _m(
        "answerability.false_fallback_rate",
        "False refusals (answerable cases)",
        GROUPS[0],
        "lower",
    ),
    _m(
        "correctness.unsupported_content_rate",
        "Answers with unsupported content",
        GROUPS[0],
        "lower",
    ),
    _m("facts.required_fact_recall", "Required facts found", GROUPS[0], "higher"),
    _m("retrieval.hit_rate_at_k", "Expected source retrieved (hit rate @k)", GROUPS[1], "higher"),
    _m(
        "retrieval.expected_page_hit_rate",
        "Expected page among the evidence",
        GROUPS[1],
        "higher",
    ),
    _m(
        "retrieval.evidence_hit_rate",
        "Expected source above the evidence threshold",
        GROUPS[1],
        "higher",
    ),
    _m("citations.citation_presence_rate", "Answers with citations", GROUPS[1], "higher"),
    _m("citations.citation_validity_rate", "Valid citation IDs", GROUPS[1], "higher"),
    _m(
        "citations.expected_source_citation_rate",
        "Answers citing an expected source",
        GROUPS[1],
        "higher",
    ),
    _m(
        "citations.cited_fact_support_rate",
        "Cited facts found in the cited passage",
        GROUPS[1],
        "higher",
    ),
    _m(
        "citations.superseded_citation_rate",
        "Superseded source cited for a current fact",
        GROUPS[1],
        "lower",
    ),
    _m("security.attack_success_rate", "Attack success (cases)", GROUPS[2], "lower"),
    _m(
        "security.attack_success_rate_by_scenario",
        "Attack success (distinct scenarios)",
        GROUPS[2],
        "lower",
    ),
    _m("security.canary_leak_rate", "Canary leaks", GROUPS[2], "lower"),
    _m(
        "security.injection_exposure_rate",
        "Attack payload reached the evidence",
        GROUPS[2],
        "neutral",
    ),
    _m(
        "security.task_completion_rate",
        "Legitimate task completed under attack",
        GROUPS[2],
        "higher",
    ),
    _m(
        "security.benign_control_success_rate",
        "Benign controls answered correctly",
        GROUPS[2],
        "higher",
    ),
    _m("security.unnecessary_refusal_rate", "Benign controls refused", GROUPS[2], "lower"),
    _m("latency.query.median_ms", "Median query latency", GROUPS[3], "lower", "ms"),
    _m("latency.query.p95_ms", "p95 query latency", GROUPS[3], "lower", "ms"),
    _m(
        "latency.query_with_generation.median_ms",
        "Median latency when the model was called",
        GROUPS[3],
        "lower",
        "ms",
    ),
    _m("judge.scored", "Answers scored by the judge", GROUPS[4], "neutral", "count"),
    _m("judge.mean_correctness", "Mean correctness (1-5)", GROUPS[4], "higher", "mean"),
    _m("judge.mean_groundedness", "Mean groundedness (1-5)", GROUPS[4], "higher", "mean"),
    _m("judge.mean_completeness", "Mean completeness (1-5)", GROUPS[4], "higher", "mean"),
    _m(
        "judge.unsupported_claim_flags",
        "Answers flagged with unsupported claims",
        GROUPS[4],
        "lower",
    ),
    _m(
        "judge.citations_support_claims",
        "Answers whose citations support the claims",
        GROUPS[4],
        "higher",
    ),
)

# Run parameters shown and compared (MLflow parameter names; the same fields exist in
# every report's `configuration` / `dataset` sections).
PARAM_LABELS: dict[str, str] = {
    "dataset.version": "Dataset version",
    "dataset.fingerprint_sha256": "Dataset fingerprint",
    "dataset.cases_run": "Cases run",
    "config.generation_provider": "Generation provider",
    "config.generation_model": "Generation model",
    "config.generation_temperature": "Generation temperature",
    "config.prompt_version": "Prompt version",
    "config.embedding_model": "Embedding model",
    "config.chunk_size_tokens": "Chunk size (tokens)",
    "config.chunk_overlap_tokens": "Chunk overlap (tokens)",
    "config.top_k": "Top-k",
    "config.min_retrieval_score": "Evidence threshold",
    "config.retrieval_index": "Retrieval index",
    "config.evaluator_version": "Evaluator version",
    "config.judge_enabled": "Judge enabled",
    "config.judge_model": "Judge model",
    "config.judge_prompt_version": "Judge prompt version",
    "report.schema_version": "Report schema",
}
