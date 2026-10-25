"""Evaluation runner: index the fixture corpus into an isolated, temporary Qdrant store
and run every case sequentially through the production `RAGPipeline`.

Isolation: a fresh temporary directory (embedded Qdrant, unique collection) is created
per run and deleted afterwards, also on errors. The configured `QDRANT_URL`,
`QDRANT_LOCAL_PATH`, and collection are never opened, so user documents are untouched.
"""

from __future__ import annotations

import logging
import re
import secrets
import shutil
import tempfile
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import Settings
from app.core.errors import AppError, ConfigurationError
from app.embeddings.base import Embedder
from app.evaluation.dataset import EvalCase, LoadedDataset
from app.evaluation.judge import JUDGE_PROMPT_VERSION, JUDGE_SEED, JUDGE_TEMPERATURE, LLMJudge
from app.evaluation.metrics import (
    EVALUATOR_VERSION,
    METRIC_DEFINITIONS,
    aggregate,
    check_attack,
    check_citation_support,
    check_citations,
    check_correct,
    check_diagnostic,
    check_facts,
    check_retrieval,
    check_superseded_citations,
    check_unsupported_content,
    classify,
)
from app.evaluation.schemas import (
    CaseError,
    CaseOutcome,
    CaseResult,
    DatasetInfo,
    ErrorStage,
    EvaluationReport,
    JudgeResult,
    RetrievedPassage,
    RunConfiguration,
    RunStatus,
)
from app.evaluation.threshold import analyse_thresholds
from app.generation.base import GenerationProvider
from app.generation.prompts import PROMPT_VERSION, source_id
from app.pipeline import EvidenceRetrieval, RAGPipeline
from app.retrieval.vector_store import RETRIEVAL_INDEX, QdrantVectorStore
from app.schemas.query import QueryRequest, QueryResponse

logger = logging.getLogger(__name__)

TEMP_PREFIX = "ragguard-eval-"

LIMITATIONS = [
    "Small synthetic dataset: every rate moves noticeably with a single case, and p95 latency "
    "equals the maximum for fewer than 20 values. Results describe this corpus, not general "
    "quality.",
    "The corpus is plain text only; PDF extraction and page-level citations are not exercised "
    "by this dataset (they are covered by the backend test suite).",
    "Prompt-injection results cover only the listed synthetic scenarios with string-based "
    "success criteria; blocked attacks here do not prove resistance to other or adaptive "
    "attacks, and paraphrased leaks of a canary would not be detected.",
    "Claim support is checked lexically per sentence; it does not verify every claim in an "
    "answer, only the dataset's required facts.",
    "Required-fact and diagnostic checks are lexical (case-insensitive, word-bounded string "
    "matches). They can miss correct paraphrases and cannot detect a fact stated with a wrong "
    "qualifier.",
    "Citation validity checks that [Sn] identifiers resolve to returned sources; it does not "
    "prove that a cited passage supports the sentence next to it. Citations written in other "
    "formats (e.g. [S1, S2]) are not recognised as citations.",
    "The LLM judge is supplementary and noisy. When the judge model equals the generation "
    "model, self-evaluation bias is likely (the model tends to rate its own answers favourably).",
    "Answerability metrics count any 'answered' status as predicting answerable, even when the "
    "text itself says that the documents do not cover the question.",
    "The threshold sweep estimates retrieval-gate classification from recorded scores; it does "
    "not guarantee answer correctness at any threshold.",
    "Local model inference is not perfectly deterministic across runs or machines, even at low "
    "temperature.",
    "Corpus ingestion time includes loading the embedding model on first use; query latency "
    "depends on whether the local LLM is already loaded and on other load on the machine.",
]


@dataclass(frozen=True)
class RunOptions:
    limit: int | None = None
    case_ids: tuple[str, ...] | None = None  # run only these cases (dataset order)
    work_dir: Path | None = None  # parent for the temporary store (default: system temp)


@dataclass(frozen=True)
class RunOutcome:
    report: EvaluationReport
    temp_dir: Path


def new_run_id(now: datetime | None = None) -> str:
    moment = now or datetime.now(UTC)
    return f"{moment.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"


def _is_within(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


@contextmanager
def isolated_store(
    settings: Settings, run_id: str, work_dir: Path | None = None
) -> Iterator[tuple[Settings, QdrantVectorStore, Path]]:
    """Yield settings and a vector store bound to a new temporary directory; always clean up."""
    user_store = settings.qdrant_local_path.resolve()
    parent = (work_dir or Path(tempfile.gettempdir())).resolve()
    if _is_within(parent, user_store):
        raise ConfigurationError(
            f"The evaluation work directory {parent} overlaps the application's Qdrant storage."
        )
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f"{TEMP_PREFIX}{run_id}-", dir=parent)).resolve()
    try:
        storage = root / "qdrant"
        if _is_within(storage, user_store) or _is_within(user_store, root):
            raise ConfigurationError("Temporary evaluation storage overlaps the application store.")
        collection = "ragguard_eval_" + re.sub(r"[^A-Za-z0-9_]", "_", run_id)
        eval_settings = settings.model_copy(
            update={
                "qdrant_url": None,
                "qdrant_api_key": None,
                "qdrant_local_path": storage,
                "qdrant_collection_name": collection,
            }
        )
        store = QdrantVectorStore.from_settings(eval_settings)
        try:
            yield eval_settings, store, root
        finally:
            store.close()
    finally:
        if root.name.startswith(TEMP_PREFIX) and root.parent == parent:
            shutil.rmtree(root, ignore_errors=True)


# --- per case --------------------------------------------------------------------
def _passages(retrieval: EvidenceRetrieval) -> list[RetrievedPassage]:
    evidence_ids = {c.point_id: source_id(i) for i, c in enumerate(retrieval.assessment.supporting)}
    # The text the model received (a passage may be merged with its region, D-072).
    supplied = {c.point_id: c.text for c in retrieval.assessment.supporting}
    withheld = {c.point_id for c in retrieval.superseded}  # passed the gate (D-070)
    return [
        RetrievedPassage(
            rank=rank,
            filename=chunk.filename,
            document_id=chunk.document_id,
            page_number=chunk.page_number,
            chunk_index=chunk.chunk_index,
            score=round(chunk.score, 4),
            above_threshold=chunk.point_id in evidence_ids or chunk.point_id in withheld,
            source_id=evidence_ids.get(chunk.point_id),
            text=supplied.get(chunk.point_id, chunk.text),
        )
        for rank, chunk in enumerate(retrieval.retrieved, start=1)
    ]


def _error(stage: ErrorStage, exc: Exception) -> CaseError:
    if isinstance(exc, AppError):
        return CaseError(stage=stage, code=exc.code, message=exc.message)
    return CaseError(stage=stage, code="unexpected_error", message=f"{type(exc).__name__}: {exc}")


def run_case(pipeline: RAGPipeline, case: EvalCase, judge: LLMJudge | None) -> CaseResult:
    request = QueryRequest(question=case.question)
    start = time.perf_counter()
    retrieval: EvidenceRetrieval | None = None
    response: QueryResponse | None = None
    error: CaseError | None = None
    try:
        retrieval = pipeline.retrieve_evidence(request)
        try:
            response = pipeline.generate_answer(request, retrieval)
        except Exception as exc:
            logger.warning("Case %s failed during generation: %s", case.id, exc)
            error = _error("generation", exc)
    except Exception as exc:
        logger.warning("Case %s failed during retrieval: %s", case.id, exc)
        error = _error("retrieval", exc)
    latency_ms = round((time.perf_counter() - start) * 1000, 1)

    passages = _passages(retrieval) if retrieval is not None else []
    outcome: CaseOutcome
    if response is None:
        outcome = "error"
    else:
        outcome = "answered" if response.status == "answered" else "fallback"
    answer = response.answer if response is not None else None
    answered = outcome == "answered" and answer is not None

    if judge is None:
        judge_result = JudgeResult(status="skipped", reason="Judging disabled for this run.")
    elif not answered or answer is None:
        reason = (
            "Fallback response: no generated content to judge."
            if outcome == "fallback"
            else "Pipeline error: no response to judge."
        )
        judge_result = JudgeResult(status="not_applicable", reason=reason)
    else:
        judge_result = judge.judge(case, answer, [p for p in passages if p.source_id])

    recorded = CaseResult(
        case_id=case.id,
        question=case.question,
        category=case.category,
        answerability=case.answerability,
        reference_answer=case.reference_answer,
        expected_sources=list(case.expected_sources),
        superseded_sources=list(case.superseded_sources),
        required_facts=[f.description for f in case.required_facts],
        notes=case.notes,
        outcome=outcome,
        answer=answer,
        fallback_reason=response.fallback_reason if response is not None else None,
        llm_called=bool(response is not None and response.generation is not None)
        or (error is not None and error.stage == "generation"),
        retrieved=passages,
        max_score=None
        if retrieval is None or retrieval.assessment.max_score is None
        else round(retrieval.assessment.max_score, 4),
        supporting_count=len(retrieval.assessment.supporting) if retrieval is not None else 0,
        latency_ms=latency_ms,
        pipeline_latency_ms=response.latency_ms if response is not None else None,
        classification=None,
        retrieval=None,
        citations=None,
        facts=None,
        citation_support=None,
        superseded_citations=[],
        unsupported_content=[],
        correct=None,
        diagnostic=None,
        attack=None,
        judge=judge_result,
        error=error,
    )
    return score_case(case, recorded)


def score_case(case: EvalCase, recorded: CaseResult) -> CaseResult:
    """Compute every deterministic check from the recorded outputs of a case.

    Uses only the recorded outcome, answer, and retrieved passages, so a saved report can
    be re-scored with the current evaluator (see `rescore_report`) without new queries.
    """
    outcome = recorded.outcome
    answer = recorded.answer
    passages = recorded.retrieved
    answered = outcome == "answered" and answer is not None
    citations = check_citations(case, answer, passages) if answered and answer else None
    facts = check_facts(case, answer) if answered and answer and case.is_answerable else None
    unsupported = check_unsupported_content(case, answer if answered else None)
    attack = check_attack(case, outcome, answer, citations, facts, passages)
    has_retrieval = recorded.max_score is not None or bool(passages)
    retrieval_failed = recorded.error is not None and recorded.error.stage == "retrieval"
    return recorded.model_copy(
        update={
            "category": case.category,
            "answerability": case.answerability,
            "reference_answer": case.reference_answer,
            "expected_sources": list(case.expected_sources),
            "superseded_sources": list(case.superseded_sources),
            "required_facts": [f.description for f in case.required_facts],
            "notes": case.notes,
            "classification": classify(case.is_answerable, outcome),
            "retrieval": check_retrieval(case, passages)
            if has_retrieval and not retrieval_failed
            else None,
            "citations": citations,
            "facts": facts,
            "citation_support": check_citation_support(case, answer, passages)
            if answered and answer
            else None,
            "superseded_citations": check_superseded_citations(case, citations),
            "unsupported_content": unsupported,
            "correct": check_correct(case, outcome, facts, unsupported, attack),
            "diagnostic": check_diagnostic(case, outcome, answer, citations, facts),
            "attack": attack,
        }
    )


def rescore_report(report: EvaluationReport, loaded: LoadedDataset) -> EvaluationReport:
    """Re-score a saved report with the current evaluator code (no model calls).

    Requires the same dataset (fingerprint) the report was produced with. Judge results,
    answers, scores, and timings are kept exactly as recorded.
    """
    if report.dataset.fingerprint_sha256 != loaded.fingerprint:
        raise ValueError(
            "The report was produced with a different dataset (fingerprint mismatch); "
            "re-scoring would compare different cases."
        )
    cases = {c.id: c for c in loaded.dataset.cases}
    results = [score_case(cases[r.case_id], r) for r in report.cases]
    old = report.aggregates
    latency = old.latency if old is not None else None
    status, detail = (
        (report.status, report.status_detail)
        if report.fatal_error
        else _status(results, report.configuration.judge_enabled)
    )
    return report.model_copy(
        update={
            "run_id": f"{report.run_id}-rescored-{secrets.token_hex(2)}",
            "status": status,
            "status_detail": detail,
            "rescored_from": report.run_id,
            "metric_definitions": METRIC_DEFINITIONS,
            "aggregates": aggregate(
                results,
                k=report.configuration.top_k,
                judge_enabled=report.configuration.judge_enabled,
                ingestion_ms=latency.ingestion_ms if latency else None,
                judge_total_ms=latency.judge_total_ms if latency else None,
                run_total_ms=latency.run_total_ms if latency else 0.0,
            )
            if results
            else None,
            "threshold_analysis": analyse_thresholds(
                results, report.configuration.min_retrieval_score
            )
            if any(r.max_score is not None for r in results)
            else None,
            "diagnostic_cases": [
                r.case_id for r in results if r.diagnostic is not None or r.attack is not None
            ],
            "cases": results,
            "limitations": LIMITATIONS,
        }
    )


# --- run -------------------------------------------------------------------------
def _status(results: list[CaseResult], judge_enabled: bool) -> tuple[RunStatus, str]:
    failed = [r.case_id for r in results if r.outcome == "error"]
    judge_errors = [r.case_id for r in results if r.judge.status == "error"]
    if results and len(failed) == len(results):
        return "failed", f"All {len(results)} cases failed in the pipeline."
    problems = []
    if failed:
        problems.append(f"{len(failed)} case(s) failed in the pipeline: {', '.join(failed)}")
    if judge_errors:
        problems.append(f"{len(judge_errors)} judge call(s) failed: {', '.join(judge_errors)}")
    if problems:
        return "partial", "; ".join(problems) + "."
    judged = "with LLM judging" if judge_enabled else "without LLM judging (skipped)"
    return "completed", f"All {len(results)} cases completed {judged}."


def _dataset_info(
    loaded: LoadedDataset,
    cases: list[EvalCase],
    limit: int | None,
    case_ids: tuple[str, ...] | None,
) -> DatasetInfo:
    return DatasetInfo(
        dataset_id=loaded.dataset.dataset_id,
        version=loaded.dataset.version,
        path=str(loaded.path),
        fingerprint_sha256=loaded.fingerprint,
        cases_in_dataset=len(loaded.dataset.cases),
        cases_run=len(cases),
        case_limit=limit,
        case_filter=list(case_ids) if case_ids else None,
        category_counts=dict(sorted(Counter(c.category for c in cases).items())),
        corpus_files={f.filename: f.sha256 for f in loaded.corpus},
    )


def _configuration(
    settings: Settings,
    embedder: Embedder,
    provider: GenerationProvider,
    judge: LLMJudge | None,
    generation_readiness: str,
    judge_readiness: str | None,
) -> RunConfiguration:
    return RunConfiguration(
        generation_provider=provider.name,
        generation_model=provider.model,
        prompt_version=PROMPT_VERSION,
        generation_temperature=settings.generation_temperature,
        generation_readiness=generation_readiness,
        judge_enabled=judge is not None,
        judge_provider=judge.provider.name if judge else None,
        judge_model=judge.provider.model if judge else None,
        judge_prompt_version=JUDGE_PROMPT_VERSION if judge else None,
        judge_temperature=JUDGE_TEMPERATURE if judge else None,
        judge_seed=JUDGE_SEED if judge else None,
        judge_readiness=judge_readiness,
        judge_same_model_as_generation=(
            judge.provider.name == provider.name and judge.provider.model == provider.model
        )
        if judge
        else None,
        embedding_model=embedder.model_name,
        chunk_size_tokens=settings.chunk_size_tokens,
        chunk_overlap_tokens=settings.chunk_overlap_tokens,
        top_k=settings.default_top_k,
        min_retrieval_score=settings.min_retrieval_score,
        vector_store="embedded Qdrant in a temporary directory (deleted after the run)",
        retrieval_index=RETRIEVAL_INDEX,
        evaluator_version=EVALUATOR_VERSION,
    )


def _readiness(provider: GenerationProvider) -> str:
    status = provider.check_readiness()
    return f"{status.state}: {status.detail}"


def run_evaluation(
    loaded: LoadedDataset,
    *,
    settings: Settings,
    embedder: Embedder,
    provider: GenerationProvider,
    judge: LLMJudge | None,
    options: RunOptions | None = None,
    run_id: str | None = None,
) -> RunOutcome:
    """Run the (already validated) dataset; always returns a report, even for failed runs."""
    options = options or RunOptions()
    run_id = run_id or new_run_id()
    started_at = datetime.now(UTC)
    run_start = time.perf_counter()
    cases = list(loaded.dataset.cases)
    if options.case_ids:
        unknown = sorted(set(options.case_ids) - {c.id for c in cases})
        if unknown:
            raise ValueError(f"Unknown case IDs: {', '.join(unknown)}")
        cases = [c for c in cases if c.id in options.case_ids]
    if options.limit:
        cases = cases[: options.limit]

    generation_readiness = _readiness(provider)
    judge_readiness = _readiness(judge.provider) if judge else None
    logger.info("Evaluation %s: %d cases; generation %s", run_id, len(cases), generation_readiness)

    results: list[CaseResult] = []
    fatal_error: str | None = None
    ingestion_ms: float | None = None
    with isolated_store(settings, run_id, options.work_dir) as (eval_settings, store, temp_dir):
        pipeline = RAGPipeline(eval_settings, embedder, store, provider)
        ingest_start = time.perf_counter()
        try:
            for file in loaded.corpus:  # once per run, through the production ingestion path
                pipeline.ingest(file.filename, file.content)
            ingestion_ms = round((time.perf_counter() - ingest_start) * 1000, 1)
        except Exception as exc:
            logger.exception("Corpus ingestion failed")
            fatal_error = f"Corpus ingestion failed: {_error('retrieval', exc).message}"

        if fatal_error is None:
            for index, case in enumerate(cases, start=1):
                result = run_case(pipeline, case, judge)
                logger.info(
                    "[%d/%d] %s -> %s (max score %s, %.0f ms)",
                    index,
                    len(cases),
                    case.id,
                    result.outcome,
                    result.max_score,
                    result.latency_ms or 0,
                )
                results.append(result)

    run_total_ms = round((time.perf_counter() - run_start) * 1000, 1)
    judge_latencies = [r.judge.latency_ms for r in results if r.judge.latency_ms is not None]
    if fatal_error is not None:
        status: RunStatus = "failed"
        detail = fatal_error
    else:
        status, detail = _status(results, judge is not None)

    report = EvaluationReport(
        run_id=run_id,
        started_at=started_at.isoformat(timespec="seconds"),
        finished_at=datetime.now(UTC).isoformat(timespec="seconds"),
        status=status,
        status_detail=detail,
        fatal_error=fatal_error,
        dataset=_dataset_info(loaded, cases, options.limit, options.case_ids),
        configuration=_configuration(
            settings, embedder, provider, judge, generation_readiness, judge_readiness
        ),
        metric_definitions=METRIC_DEFINITIONS,
        aggregates=aggregate(
            results,
            k=settings.default_top_k,
            judge_enabled=judge is not None,
            ingestion_ms=ingestion_ms,
            judge_total_ms=round(sum(judge_latencies), 1) if judge else None,
            run_total_ms=run_total_ms,
        )
        if results
        else None,
        threshold_analysis=analyse_thresholds(results, settings.min_retrieval_score)
        if any(r.max_score is not None for r in results)
        else None,
        diagnostic_cases=[
            r.case_id for r in results if r.diagnostic is not None or r.attack is not None
        ],
        cases=results,
        limitations=LIMITATIONS,
    )
    return RunOutcome(report=report, temp_dir=temp_dir)
