"""Read-only views of saved evaluation reports (`GET /evaluations...`).

These are derived from `evaluation/results/<run_id>/report.json` by
`app/evaluation/results.py`. Fields a report does not contain (older schema versions)
are null or `available: false`, never zero.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.evaluation.catalog import Direction, MetricKind


class MetricValue(BaseModel):
    key: str = Field(description="JSON path in the report aggregates = MLflow metric name.")
    label: str
    group: str
    direction: Direction
    kind: MetricKind
    supplementary: bool = Field(description="LLM-judge metric: supplementary, never a verdict.")
    available: bool = Field(description="False when the report or run does not record it.")
    value: float | None = Field(description="Null when unavailable or no case applied.")
    numerator: float | None
    denominator: int | None


class EvaluationSummary(BaseModel):
    run_id: str
    readable: bool
    problem: str | None = Field(description="Why the report could not be read, if it could not.")
    schema_version: str | None
    detail_supported: bool = Field(description="Case-level detail is available (schema 1 or 2).")
    started_at: str | None
    finished_at: str | None
    status: str | None = Field(description="Execution status: completed, partial, failed.")
    status_detail: str | None
    rescored_from: str | None
    dataset_id: str | None
    dataset_version: str | None
    dataset_fingerprint: str | None
    cases_run: int | None
    cases_in_dataset: int | None
    params: dict[str, str] = Field(description="Whitelisted configuration, as logged to MLflow.")
    headline: list[MetricValue]


class LatencySummary(BaseModel):
    count: int
    mean_ms: float | None
    median_ms: float | None
    p95_ms: float | None
    min_ms: float | None
    max_ms: float | None


class JudgeSummary(BaseModel):
    enabled: bool
    model: str | None
    same_model_as_generation: bool | None
    eligible_cases: int | None
    scored: int | None
    not_applicable: int | None
    errors: list[str]


FindingKind = Literal[
    "pipeline_error",
    "false_refusal",
    "false_answer",
    "missing_facts",
    "unsupported_content",
    "attack_succeeded",
    "canary_leak",
    "invalid_citation",
    "superseded_citation",
    "unsupported_citation",
    "uncited_fact",
    "retrieval_miss",
    "judge_error",
    "judge_flag",
]


class Finding(BaseModel):
    kind: FindingKind
    detail: str


class PassageView(BaseModel):
    rank: int
    filename: str
    page_number: int | None
    score: float
    above_threshold: bool
    source_id: str | None
    cited: bool
    excerpt: str = Field(description="Start of the passage text (truncated).")


class AttackView(BaseModel):
    scenario_id: str
    vector: str
    channel: str
    status: str
    reasons: list[str]
    canary_leaked: bool | None
    echoed: list[str]
    task_completed: bool | None


class JudgeView(BaseModel):
    status: str
    correctness: int | None = None
    groundedness: int | None = None
    completeness: int | None = None
    unsupported_claims: bool | None = None
    citations_support_claims: bool | None = None
    unanswerable_handled_correctly: bool | None = None
    rationale: str | None = None
    error: str | None = None


class CaseView(BaseModel):
    case_id: str
    category: str
    answerability: str
    question: str
    reference_answer: str | None
    expected_sources: list[str]
    superseded_sources: list[str]
    required_facts: list[str]
    notes: str | None
    verdict: Literal["pass", "fail", "error", "unscored"] = Field(
        description="Deterministic case verdict; 'unscored' for reports without one."
    )
    outcome: str | None
    fallback_reason: str | None
    answer: str | None
    llm_called: bool | None
    max_score: float | None
    latency_ms: float | None
    facts_found: list[str]
    facts_missing: list[str]
    cited_filenames: list[str]
    invalid_citation_ids: list[str]
    findings: list[Finding]
    attack: AttackView | None
    diagnostic: str | None
    judge: JudgeView | None
    error: str | None
    retrieved: list[PassageView]


class MetricDefinitionView(BaseModel):
    name: str
    definition: str
    denominator: str


class EvaluationDetail(BaseModel):
    summary: EvaluationSummary
    fatal_error: str | None
    metrics: list[MetricValue]
    latency: dict[str, LatencySummary]
    judge: JudgeSummary | None
    cases: list[CaseView]
    metric_definitions: list[MetricDefinitionView]
    limitations: list[str]


class EvaluationList(BaseModel):
    results_dir: str = Field(description="Repository-relative location of the reports.")
    reports: list[EvaluationSummary] = Field(description="Newest first.")
