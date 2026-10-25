"""Pydantic models for per-case results and the evaluation report.

The JSON report is `EvaluationReport.model_dump_json()`; the Markdown report is
rendered from the same object. `REPORT_SCHEMA_VERSION` changes whenever a field is
renamed or removed, so later stages (MLflow logging, the Evaluation view) can rely on it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.evaluation.dataset import (
    Answerability,
    AttackChannel,
    AttackVector,
    Category,
    DiagnosticKind,
)
from app.schemas.query import LatencyBreakdown

REPORT_SCHEMA_VERSION = "2.0"

CaseOutcome = Literal["answered", "fallback", "error"]
Classification = Literal["TP", "FP", "TN", "FN"]
RunStatus = Literal["completed", "partial", "failed"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- per case --------------------------------------------------------------------
class RetrievedPassage(_Model):
    rank: int = Field(description="1-based rank in the Qdrant result list.")
    filename: str
    document_id: str
    page_number: int | None
    chunk_index: int
    score: float = Field(description="Cosine similarity reported by Qdrant.")
    above_threshold: bool
    source_id: str | None = Field(description="Evidence label (S1..) when sent to the model.")
    text: str


class RetrievalCheck(_Model):
    expected_sources: list[str]
    retrieved_sources: list[str] = Field(description="Distinct filenames in rank order.")
    evidence_sources: list[str] = Field(description="Distinct filenames above the threshold.")
    hit_at_k: bool | None = Field(description="Null when the case has no expected sources.")
    evidence_hit: bool | None
    coverage: float | None = Field(description="Expected sources retrieved / expected sources.")
    first_expected_rank: int | None
    expected_page_hit: bool | None = Field(
        default=None,
        description="An evidence passage comes from an expected page (cases with expected_pages).",
    )


class CitationCheck(_Model):
    cited_ids: list[str] = Field(description="Every [Sn] token in the answer, first-seen order.")
    valid_ids: list[str]
    invalid_ids: list[str]
    cited_filenames: list[str]
    unexpected_filenames: list[str]
    cites_expected_source: bool | None


class FactCheck(_Model):
    facts_total: int
    facts_found: int
    found: list[str]
    missing: list[str]


class CitationSupport(_Model):
    """Lexical claim-support check: for each required fact found in the answer, does a
    sentence stating it cite a passage whose text contains the fact?"""

    facts_in_answer: list[str]
    supported: list[str]
    uncited: list[str] = Field(
        description="Fact stated without any valid citation in its sentence."
    )
    unsupported: list[str] = Field(description="Fact cited, but no cited passage contains it.")


class AttackResult(_Model):
    scenario_id: str
    vector: AttackVector
    channel: AttackChannel
    status: Literal["blocked", "succeeded", "error"]
    reasons: list[str] = Field(description="Which success criteria fired.")
    canary_leaked: bool | None
    echoed: list[str] = Field(description="Injected wording repeated (does not count as success).")
    task_completed: bool | None = Field(description="Legitimate task done (answerable cases).")
    injection_in_evidence: bool | None = Field(
        default=None,
        description="A passage of an injection source was sent to the model as evidence; "
        "null for user-query attacks and for reports scored before this field existed.",
    )


class DiagnosticResult(_Model):
    kind: DiagnosticKind
    stale_value_mentioned: bool | None = None
    current_value_mentioned: bool | None = None
    acknowledges_limitation: bool | None = None
    cited_filenames: list[str] = Field(default_factory=list)
    matched_terms: dict[str, list[str]] = Field(default_factory=dict)
    finding: str


class JudgeVerdict(_Model):
    """Validated judge output. Scores are null where the rubric marks them not applicable."""

    correctness: int | None = Field(default=None, ge=1, le=5)
    groundedness: int = Field(ge=1, le=5)
    completeness: int | None = Field(default=None, ge=1, le=5)
    unsupported_claims: bool
    citations_support_claims: bool | None = None
    unanswerable_handled_correctly: bool | None = None
    rationale: str = Field(min_length=1, max_length=2000)


class JudgeResult(_Model):
    status: Literal["scored", "not_applicable", "skipped", "error"]
    reason: str | None = None
    verdict: JudgeVerdict | None = None
    attempts: int = 0
    error: str | None = None
    raw_output: str | None = Field(default=None, description="Last raw output on failure.")
    latency_ms: float | None = None


ErrorStage = Literal["retrieval", "generation"]


class CaseError(_Model):
    stage: ErrorStage
    code: str
    message: str


class CaseResult(_Model):
    case_id: str
    question: str
    category: Category
    answerability: Answerability
    reference_answer: str | None
    expected_sources: list[str]
    superseded_sources: list[str]
    required_facts: list[str]
    notes: str

    outcome: CaseOutcome
    answer: str | None
    fallback_reason: Literal["no_results", "below_threshold", "model_declined"] | None
    llm_called: bool
    retrieved: list[RetrievedPassage]
    max_score: float | None
    supporting_count: int
    latency_ms: float | None = Field(description="End-to-end query time (monotonic clock).")
    pipeline_latency_ms: LatencyBreakdown | None

    classification: Classification | None
    retrieval: RetrievalCheck | None
    citations: CitationCheck | None
    facts: FactCheck | None
    citation_support: CitationSupport | None
    superseded_citations: list[str] = Field(
        description="Superseded sources cited for a non-historical question."
    )
    unsupported_content: list[str] = Field(
        description="Forbidden strings/patterns of the case found in the answer."
    )
    correct: bool | None = Field(
        description="Deterministic verdict: answerable = answered with all required facts, no "
        "unsupported content, no successful attack; unanswerable = fallback with no unsupported "
        "content. Null on pipeline error."
    )
    diagnostic: DiagnosticResult | None
    attack: AttackResult | None
    judge: JudgeResult
    error: CaseError | None


# --- aggregates ------------------------------------------------------------------
class Metric(_Model):
    """A rate or mean with its denominator. `value` is null when the denominator is 0."""

    value: float | None
    numerator: float | None
    denominator: int


class ConfusionMatrix(_Model):
    """Positive class = answerable. Predicted positive = the pipeline answered."""

    tp: int
    fp: int
    tn: int
    fn: int


class ClassificationScores(_Model):
    confusion: ConfusionMatrix
    precision: Metric
    recall: Metric
    f1: Metric
    correct_fallback_rate: Metric
    false_answer_rate: Metric
    false_fallback_rate: Metric


class RetrievalMetrics(_Model):
    k: int
    hit_rate_at_k: Metric
    evidence_hit_rate: Metric
    mean_coverage: Metric
    multi_source_coverage: Metric
    by_category: dict[str, Metric]
    retrieval_errors: list[str]
    misses: list[str] = Field(description="Answerable cases retrieved without any expected source.")
    expected_page_hit_rate: Metric | None = Field(
        default=None, description="Cases with expected_pages whose evidence includes such a page."
    )
    page_misses: list[str] = Field(default_factory=list)


class CitationMetrics(_Model):
    answered_cases: int
    answers_without_citations: list[str]
    citation_presence_rate: Metric
    citation_validity_rate: Metric
    invalid_citation_count: int
    expected_source_citation_rate: Metric
    cited_source_precision: Metric
    unexpected_citation_count: int
    cited_fact_support_rate: Metric
    uncited_fact_count: int
    unsupported_citation_fact_count: int
    superseded_citation_rate: Metric
    superseded_citation_cases: list[str]


class CorrectnessMetrics(_Model):
    case_pass_rate: Metric
    answer_correct_rate: Metric
    answer_failures: list[str] = Field(description="Answerable cases answered but not correct.")
    false_refusals: list[str] = Field(description="Answerable cases that fell back.")
    unsupported_content_rate: Metric
    unsupported_content_cases: list[str]
    by_category: dict[str, Metric]


class SecurityMetrics(_Model):
    attack_cases: int
    distinct_scenarios: int
    attack_success_rate: Metric
    attack_success_rate_by_scenario: Metric = Field(
        description="Scenarios with at least one successful case / scenarios evaluated."
    )
    succeeded_cases: list[str]
    canary_leak_rate: Metric
    leaked_cases: list[str]
    echo_cases: list[str]
    task_completion_rate: Metric = Field(description="Answerable attack cases.")
    by_vector: dict[str, Metric]
    by_channel: dict[str, Metric]
    errors: list[str]
    benign_control_success_rate: Metric
    unnecessary_refusal_rate: Metric
    benign_failures: list[str]
    # Added in the pre-demo pass; optional so earlier reports still validate.
    injection_exposure_rate: Metric | None = Field(
        default=None,
        description="Document attacks whose injection source reached the evidence passages.",
    )
    unexposed_attack_cases: list[str] = Field(
        default_factory=list,
        description="Document attacks whose payload never reached the model (not a defence).",
    )


class AnswerabilityMetrics(ClassificationScores):
    unclassified_errors: list[str]
    fallback_reasons: dict[str, int]
    outcomes_by_category: dict[str, dict[str, int]]


class FactMetrics(_Model):
    required_fact_recall: Metric
    complete_answer_rate: Metric
    incomplete_cases: list[str]


class LatencyStats(_Model):
    count: int
    mean_ms: float | None
    median_ms: float | None
    p95_ms: float | None
    min_ms: float | None
    max_ms: float | None


class LatencyMetrics(_Model):
    query: LatencyStats
    query_with_generation: LatencyStats
    query_without_generation: LatencyStats
    by_category: dict[str, LatencyStats]
    ingestion_ms: float | None
    judge_total_ms: float | None
    run_total_ms: float


class JudgeMetrics(_Model):
    enabled: bool
    eligible_cases: int
    scored: int
    errors: list[str]
    not_applicable: int
    skipped: int
    mean_correctness: Metric
    mean_groundedness: Metric
    mean_completeness: Metric
    unsupported_claim_flags: Metric
    unanswerable_handled_correctly: Metric
    citations_support_claims: Metric


class Aggregates(_Model):
    cases_total: int
    cases_completed: int
    cases_failed: int
    retrieval: RetrievalMetrics
    answerability: AnswerabilityMetrics
    citations: CitationMetrics
    facts: FactMetrics
    correctness: CorrectnessMetrics
    security: SecurityMetrics
    latency: LatencyMetrics
    judge: JudgeMetrics


class ThresholdPoint(ClassificationScores):
    threshold: float
    pass_rate_by_category: dict[str, Metric] = Field(
        description="Share of cases in each category whose max score reaches the threshold."
    )
    estimated_end_to_end: ClassificationScores | None = Field(
        description="Retrieval gate combined with the recorded model decision; only for "
        "thresholds >= the run threshold (see interpretation notes)."
    )


class ScoreDistribution(_Model):
    count: int
    min: float | None
    median: float | None
    max: float | None


class ThresholdCase(_Model):
    case_id: str
    category: Category
    answerability: Answerability
    max_score: float | None
    passes_run_threshold: bool | None
    outcome: CaseOutcome
    classification: Classification | None


class HighSimilarityFailure(_Model):
    case_id: str
    category: Category
    max_score: float
    outcome: CaseOutcome
    problem: str


class ThresholdAnalysis(_Model):
    run_threshold: float
    candidates: list[float]
    points: list[ThresholdPoint]
    selected: ThresholdPoint
    best_retrieval_f1_thresholds: list[float]
    score_distribution: dict[str, ScoreDistribution]
    lowest_answerable_max_score: float | None
    highest_unanswerable_max_score: float | None
    overlapping_cases: list[str]
    high_similarity_failures: list[HighSimilarityFailure]
    excluded_cases: list[str]
    per_case: list[ThresholdCase]
    notes: list[str]


class MetricDefinition(_Model):
    name: str
    definition: str
    denominator: str


class DatasetInfo(_Model):
    dataset_id: str
    version: str
    path: str
    fingerprint_sha256: str
    cases_in_dataset: int
    cases_run: int
    case_limit: int | None
    case_filter: list[str] | None = None
    category_counts: dict[str, int]
    corpus_files: dict[str, str] = Field(description="Filename -> sha256.")


class RunConfiguration(_Model):
    generation_provider: str
    generation_model: str
    prompt_version: str
    generation_temperature: float
    generation_readiness: str
    judge_enabled: bool
    judge_provider: str | None
    judge_model: str | None
    judge_prompt_version: str | None
    judge_temperature: float | None
    judge_seed: int | None
    judge_readiness: str | None
    judge_same_model_as_generation: bool | None
    embedding_model: str
    chunk_size_tokens: int
    chunk_overlap_tokens: int
    top_k: int
    min_retrieval_score: float
    vector_store: str
    retrieval_index: str | None = Field(
        default=None, description="Index format (D-063); null in reports made before it."
    )
    evaluator_version: str | None = Field(
        default=None,
        description="Version of the deterministic checks (D-068); null means e1 (before it).",
    )


class EvaluationReport(_Model):
    schema_version: str = REPORT_SCHEMA_VERSION
    run_id: str
    started_at: str
    finished_at: str
    status: RunStatus
    status_detail: str
    fatal_error: str | None
    rescored_from: str | None = Field(
        default=None, description="Run ID whose recorded outputs were re-scored, if any."
    )
    dataset: DatasetInfo
    configuration: RunConfiguration
    metric_definitions: list[MetricDefinition]
    aggregates: Aggregates | None
    threshold_analysis: ThresholdAnalysis | None
    diagnostic_cases: list[str] = Field(
        description="IDs of diagnostic cases (reported separately)."
    )
    cases: list[CaseResult]
    limitations: list[str]
