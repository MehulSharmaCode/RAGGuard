"""Command-line entry point for the offline evaluation.

Run from `backend/` with the project virtualenv:

    .venv/bin/python -m app.evaluation.run_evaluation                # full run with judge
    .venv/bin/python -m app.evaluation.run_evaluation --skip-judge   # RAG queries only
    .venv/bin/python -m app.evaluation.run_evaluation --limit 5      # quick check
    .venv/bin/python -m app.evaluation.run_evaluation --validate-only

    .venv/bin/python -m app.evaluation.run_evaluation --no-tracking  # no MLflow run
    .venv/bin/python -m app.evaluation.run_evaluation --import-report PATH --label legacy

Every run is logged to MLflow (local SQLite store `mlflow.db` in the repository unless
MLFLOW_TRACKING_URI / --tracking-uri says otherwise) unless --no-tracking is given.

Exit codes: 0 completed, 1 partial (some cases or judge calls failed), 2 failed run or
invalid dataset, 3 reports written but MLflow tracking failed. They describe execution,
not a quality verdict.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.embeddings.sentence_transformer import SentenceTransformerEmbedder
from app.evaluation.dataset import DatasetValidationError, LoadedDataset, load_dataset
from app.evaluation.judge import LLMJudge, build_judge_provider
from app.evaluation.report import fmt_metric, write_reports
from app.evaluation.runner import RunOptions, rescore_report, run_evaluation
from app.evaluation.schemas import EvaluationReport
from app.generation.factory import build_provider
from app.tracking.mlflow_tracking import TrackingError, git_revision, log_report, resolve_config

EXIT_CODES = {"completed": 0, "partial": 1, "failed": 2}
EXIT_TRACKING_FAILED = 3


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.evaluation.run_evaluation",
        description="Run the RAGGuard evaluation dataset through the production RAG pipeline "
        "in an isolated temporary vector store, write JSON and Markdown reports, and log the "
        "run to MLflow.",
    )
    parser.add_argument(
        "--dataset", type=Path, help="dataset JSON file (default: EVALUATION_DATASET_PATH)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="reports go to <dir>/<run_id>/ (default: EVALUATION_RESULTS_DIR, evaluation/results)",
    )
    parser.add_argument("--limit", type=_positive, help="run only the first N cases")
    parser.add_argument(
        "--cases", help="comma-separated case IDs to run (e.g. for repeated runs of a scenario)"
    )
    parser.add_argument(
        "--skip-judge", action="store_true", help="skip LLM judging (answers are still generated)"
    )
    parser.add_argument("--judge-model", help="Ollama model for the judge (default: OLLAMA_MODEL)")
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="parent directory for temporary storage (default: system temp)",
    )
    parser.add_argument(
        "--validate-only", action="store_true", help="validate the dataset and exit"
    )
    tracking = parser.add_argument_group("MLflow tracking")
    tracking.add_argument(
        "--no-tracking", action="store_true", help="do not log this run to MLflow"
    )
    tracking.add_argument(
        "--tracking-uri", help="MLflow tracking URI (default: MLFLOW_TRACKING_URI or ./mlflow.db)"
    )
    tracking.add_argument("--experiment", help="MLflow experiment (default: ragguard-evaluation)")
    tracking.add_argument("--label", help="free-text label stored as the MLflow tag ragguard.label")
    parser.add_argument(
        "--rescore",
        type=Path,
        help="re-score a saved schema-2 report.json with the current evaluator (no model calls)",
    )
    tracking.add_argument(
        "--import-report",
        type=Path,
        help="log an existing report.json (and the report.md next to it) instead of running",
    )
    return parser.parse_args(argv)


def _track(
    args: argparse.Namespace,
    settings: Settings,
    report: dict[str, object],
    paths: list[Path],
    extra_tags: dict[str, str],
) -> int:
    config = resolve_config(
        args.tracking_uri or settings.mlflow_tracking_uri,
        args.experiment or settings.mlflow_experiment_name,
        settings.mlflow_artifact_root,
    )
    tags = {**git_revision(), **extra_tags}
    if args.label:
        tags["ragguard.label"] = args.label
    try:
        tracked = log_report(report, paths, config, tags=tags)
    except TrackingError as exc:
        print(
            f"ERROR: {exc}. The reports were written; rerun with --import-report.", file=sys.stderr
        )
        return EXIT_TRACKING_FAILED
    print(
        f"MLflow: run {tracked.run_id} in experiment '{tracked.experiment_name}' "
        f"({len(tracked.params)} params, {len(tracked.metrics)} metrics) at {tracked.tracking_uri}"
    )
    return 0


def _import_report(args: argparse.Namespace, settings: Settings) -> int:
    path = args.import_report.resolve()
    report = json.loads(path.read_text(encoding="utf-8"))
    paths = [path] + [p for p in [path.with_name("report.md")] if p.exists()]
    print(f"Importing {path} (run {report.get('run_id')}, schema {report.get('schema_version')})")
    tags = {"ragguard.imported": "true", "ragguard.source_report": str(path)}
    return _track(args, settings, report, paths, tags)


def _rescore(args: argparse.Namespace, settings: Settings, loaded: LoadedDataset) -> int:
    source = args.rescore.resolve()
    original = EvaluationReport.model_validate_json(source.read_text(encoding="utf-8"))
    try:
        report = rescore_report(original, loaded)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    json_path, md_path = write_reports(report, args.output_dir.resolve())
    print(f"Re-scored {original.run_id} -> {report.run_id}: {report.status}")
    print(f"Reports:\n  {json_path}\n  {md_path}")
    if args.no_tracking:
        return EXIT_CODES[report.status]
    tags = {"ragguard.rescored_from": original.run_id}
    code = _track(args, settings, report.model_dump(mode="json"), [json_path, md_path], tags)
    return code or EXIT_CODES[report.status]


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    args.dataset = args.dataset or settings.evaluation_dataset_path
    args.output_dir = args.output_dir or settings.evaluation_results_dir
    configure_logging(settings.log_level)
    logging.getLogger("app.pipeline").setLevel(logging.WARNING)  # one line per case is enough

    if args.import_report:
        if args.no_tracking:
            print("--import-report needs tracking; remove --no-tracking.", file=sys.stderr)
            return 2
        return _import_report(args, settings)

    try:
        loaded = load_dataset(args.dataset.resolve())
    except DatasetValidationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        f"Dataset valid: {loaded.dataset.dataset_id} v{loaded.dataset.version}, "
        f"{len(loaded.dataset.cases)} cases, {len(loaded.corpus)} corpus files, "
        f"sha256 {loaded.fingerprint[:16]}…"
    )
    if args.validate_only:
        return 0
    if args.rescore:
        return _rescore(args, settings, loaded)

    case_ids = tuple(c.strip() for c in args.cases.split(",") if c.strip()) if args.cases else None
    provider = build_provider(settings)
    judge = None if args.skip_judge else LLMJudge(build_judge_provider(settings, args.judge_model))
    try:
        outcome = run_evaluation(
            loaded,
            settings=settings,
            embedder=SentenceTransformerEmbedder(settings.embedding_model),
            provider=provider,
            judge=judge,
            options=RunOptions(limit=args.limit, case_ids=case_ids, work_dir=args.work_dir),
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    report = outcome.report
    json_path, md_path = write_reports(report, args.output_dir.resolve())

    print(f"\nRun {report.run_id}: {report.status} — {report.status_detail}")
    a = report.aggregates
    if a is not None:
        rows = [
            ("case pass rate", a.correctness.case_pass_rate),
            ("correct answers (answerable)", a.correctness.answer_correct_rate),
            ("false-answer rate", a.answerability.false_answer_rate),
            ("false-fallback rate", a.answerability.false_fallback_rate),
            ("attack success rate", a.security.attack_success_rate),
            ("canary leak rate", a.security.canary_leak_rate),
            ("benign-control success", a.security.benign_control_success_rate),
            (f"hit rate@{a.retrieval.k}", a.retrieval.hit_rate_at_k),
            ("citation validity", a.citations.citation_validity_rate),
            ("cited-fact support", a.citations.cited_fact_support_rate),
        ]
        if a.judge.enabled:
            rows.append(("judge correctness (supp.)", a.judge.mean_correctness))
        for name, metric in rows:
            print(f"  {name:<30} {fmt_metric(metric)}")
        print(f"  {'median query latency ms':<30} {a.latency.query.median_ms}")
    print(f"Reports:\n  {json_path}\n  {md_path}")
    print(f"Temporary store removed: {not outcome.temp_dir.exists()}")

    status_code = EXIT_CODES[report.status]
    if args.no_tracking:
        print("MLflow tracking disabled for this run (--no-tracking).")
        return status_code
    tracking_code = _track(args, settings, report.model_dump(mode="json"), [json_path, md_path], {})
    return tracking_code or status_code


if __name__ == "__main__":
    raise SystemExit(main())
