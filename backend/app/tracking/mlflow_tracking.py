"""Local-first MLflow tracking for evaluation reports.

Each evaluation run becomes one MLflow run in a named experiment: whitelisted
configuration as parameters, the report's aggregates as metrics (same names as the
JSON paths, e.g. `security.attack_success_rate`), and the JSON/Markdown reports plus a
failure summary as artifacts. Nothing outside the whitelist is logged, so settings
values such as API keys can never reach MLflow.

`mlflow` is imported lazily: the API and the RAG pipeline never import this module.
A tracking failure raises `TrackingError`; callers decide how to report it (the CLI
exits non-zero) instead of silently continuing.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.core.config import REPO_ROOT

if TYPE_CHECKING:
    from mlflow.tracking import MlflowClient

DEFAULT_EXPERIMENT = "ragguard-evaluation"
DEFAULT_TRACKING_URI = f"sqlite:///{REPO_ROOT / 'mlflow.db'}"
DEFAULT_ARTIFACT_ROOT = REPO_ROOT / "mlartifacts"
_PARAM_LIMIT = 500  # characters; MLflow allows more, but parameters should stay short

# Report fields logged as parameters (anything else is never logged as a parameter).
_CONFIG_PARAMS = (
    "generation_provider",
    "generation_model",
    "prompt_version",
    "generation_temperature",
    "judge_enabled",
    "judge_provider",
    "judge_model",
    "judge_prompt_version",
    "judge_temperature",
    "judge_seed",
    "judge_same_model_as_generation",
    "embedding_model",
    "chunk_size_tokens",
    "chunk_overlap_tokens",
    "top_k",
    "min_retrieval_score",
    "retrieval_index",
    "evaluator_version",
)
_DATASET_PARAMS = (
    "dataset_id",
    "version",
    "fingerprint_sha256",
    "cases_in_dataset",
    "cases_run",
    "case_limit",
)


class TrackingError(Exception):
    """MLflow logging failed; the evaluation reports on disk are unaffected."""


@dataclass(frozen=True)
class TrackingConfig:
    tracking_uri: str = DEFAULT_TRACKING_URI
    experiment_name: str = DEFAULT_EXPERIMENT
    artifact_root: Path = DEFAULT_ARTIFACT_ROOT  # used only when creating the experiment


@dataclass(frozen=True)
class TrackedRun:
    run_id: str
    experiment_id: str
    experiment_name: str
    tracking_uri: str
    params: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)


def resolve_config(tracking_uri: str | None, experiment_name: str | None = None) -> TrackingConfig:
    """Explicit value > `MLFLOW_TRACKING_URI` setting > local SQLite store in the repo."""
    return TrackingConfig(
        tracking_uri=tracking_uri or DEFAULT_TRACKING_URI,
        experiment_name=experiment_name or DEFAULT_EXPERIMENT,
    )


def git_revision(repo: Path = REPO_ROOT) -> dict[str, str]:
    """Current commit and whether the working tree has uncommitted changes."""

    def run(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=10
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    commit = run("rev-parse", "HEAD")
    status = run("status", "--porcelain")
    return {
        "git_commit": commit or "unavailable",
        "git_dirty": "unknown" if status is None else str(bool(status)).lower(),
    }


def _value(value: Any) -> str:
    text = (
        "null" if value is None else str(value).lower() if isinstance(value, bool) else str(value)
    )
    return text[:_PARAM_LIMIT]


def extract_params(report: Mapping[str, Any]) -> dict[str, str]:
    """Whitelisted parameters from a report dict (schema 1.x or 2.x)."""
    config = report.get("configuration") or {}
    dataset = report.get("dataset") or {}
    params = {f"config.{k}": _value(config.get(k)) for k in _CONFIG_PARAMS if k in config}
    params.update({f"dataset.{k}": _value(dataset.get(k)) for k in _DATASET_PARAMS if k in dataset})
    params["report.schema_version"] = _value(report.get("schema_version"))
    return params


def _walk(prefix: str, node: Any) -> Iterator[tuple[str, float]]:
    if isinstance(node, bool | int | float):
        yield prefix, float(node)
    elif isinstance(node, Mapping):
        if {"value", "numerator", "denominator"} <= node.keys():  # a rate or mean
            if node["value"] is not None:
                yield prefix, float(node["value"])
            yield f"{prefix}.denominator", float(node["denominator"])
            return
        for key, child in node.items():
            yield from _walk(f"{prefix}.{key}" if prefix else str(key), child)
    # lists (case IDs) and strings are not metrics


def extract_metrics(report: Mapping[str, Any]) -> dict[str, float]:
    """Numeric aggregates keyed by their JSON path; null rates are omitted, not zero."""
    metrics = dict(_walk("", report.get("aggregates") or {}))
    analysis = report.get("threshold_analysis") or {}
    selected = analysis.get("selected")
    if selected:
        for name, value in _walk("threshold.run", selected):
            if not name.startswith("threshold.run.pass_rate_by_category"):
                metrics[name] = value
    return metrics


def _sweep_series(report: Mapping[str, Any]) -> list[tuple[str, float, int]]:
    """Gate F1 / false-answer / false-fallback rates per threshold, step = threshold * 100."""
    series: list[tuple[str, float, int]] = []
    for point in (report.get("threshold_analysis") or {}).get("points", []):
        step = round(float(point["threshold"]) * 100)
        for name in ("f1", "false_answer_rate", "false_fallback_rate"):
            value = (point.get(name) or {}).get("value")
            if value is not None:
                series.append((f"threshold_sweep.{name}", float(value), step))
    return series


def failure_summary(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Compact per-case failures (IDs, failed checks, truncated synthetic answer)."""
    rows: list[dict[str, Any]] = []
    for case in report.get("cases", []):
        attack = case.get("attack") or {}
        problems: list[str] = []
        if case.get("error"):
            problems.append(f"error: {case['error'].get('code')}")
        if case.get("correct") is False:
            problems.append("incorrect")
        if attack.get("status") == "succeeded":
            problems.append("attack succeeded: " + "; ".join(attack.get("reasons", [])))
        if case.get("unsupported_content"):
            problems.append("unsupported content: " + ", ".join(case["unsupported_content"]))
        if case.get("superseded_citations"):
            problems.append("superseded cited: " + ", ".join(case["superseded_citations"]))
        if (case.get("judge") or {}).get("status") == "error":
            problems.append("judge error")
        if problems:
            rows.append(
                {
                    "case_id": case.get("case_id"),
                    "category": case.get("category"),
                    "outcome": case.get("outcome"),
                    "fallback_reason": case.get("fallback_reason"),
                    "problems": problems,
                    "answer_excerpt": (case.get("answer") or "")[:500],
                }
            )
    return rows


def _default_client(tracking_uri: str) -> MlflowClient:
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    from mlflow.tracking import MlflowClient

    return MlflowClient(tracking_uri=tracking_uri)


def log_report(
    report: Mapping[str, Any],
    report_paths: list[Path],
    config: TrackingConfig,
    *,
    run_name: str | None = None,
    tags: Mapping[str, str] | None = None,
    client_factory: Callable[[str], MlflowClient] = _default_client,
) -> TrackedRun:
    """Log one evaluation report as an MLflow run. Raises TrackingError on any failure."""
    run_id: str | None = None
    client: MlflowClient | None = None
    try:
        client = client_factory(config.tracking_uri)
        experiment = client.get_experiment_by_name(config.experiment_name)
        if experiment is None:
            experiment_id = client.create_experiment(
                config.experiment_name, artifact_location=config.artifact_root.resolve().as_uri()
            )
        else:
            experiment_id = experiment.experiment_id
        params = extract_params(report)
        metrics = extract_metrics(report)
        all_tags = {
            "ragguard.run_id": str(report.get("run_id")),
            "ragguard.status": str(report.get("status")),
            "ragguard.started_at": str(report.get("started_at")),
            "ragguard.dataset_fingerprint": str(
                (report.get("dataset") or {}).get("fingerprint_sha256")
            ),
            **(tags or {}),
        }
        run = client.create_run(
            experiment_id, run_name=run_name or str(report.get("run_id")), tags=all_tags
        )
        run_id = run.info.run_id
        for key, value in params.items():
            client.log_param(run_id, key, value)
        for key, metric in metrics.items():
            client.log_metric(run_id, key, metric)
        for key, metric, step in _sweep_series(report):
            client.log_metric(run_id, key, metric, step=step)
        for path in report_paths:
            client.log_artifact(run_id, str(path), artifact_path="reports")
        with tempfile.TemporaryDirectory() as tmp:
            summary = Path(tmp) / "failures.json"
            summary.write_text(json.dumps(failure_summary(report), indent=2), encoding="utf-8")
            client.log_artifact(run_id, str(summary), artifact_path="reports")
        client.set_terminated(run_id, "FINISHED")
        return TrackedRun(
            run_id=run_id,
            experiment_id=experiment_id,
            experiment_name=config.experiment_name,
            tracking_uri=config.tracking_uri,
            params=params,
            metrics=metrics,
        )
    except Exception as exc:
        if client is not None and run_id is not None:
            # The original error is the one to report.
            with contextlib.suppress(Exception):
                client.set_terminated(run_id, "FAILED")
        raise TrackingError(f"MLflow tracking failed ({config.tracking_uri}): {exc}") from exc
