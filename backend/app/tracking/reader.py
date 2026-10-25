"""Read-only access to the MLflow evaluation runs for the API's Experiments view.

Uses the same tracking configuration as the evaluation CLI (`MLFLOW_TRACKING_URI`, else
the repository's `mlflow.db`; experiment `MLFLOW_EXPERIMENT_NAME`). It never creates a
store, experiment, or run: a local SQLite store that does not exist is reported as
`no_store` instead of being opened (opening it would create an empty database).

`mlflow` is imported lazily on the first request to an experiments endpoint; the query
path never imports it, and a missing installation is reported as
`dependency_missing`, never as "zero runs". Only whitelisted tags, the logged
(already whitelisted) parameters, metrics, and three report artifacts are exposed.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from app.core.config import REPO_ROOT
from app.core.errors import (
    ArtifactNotFoundError,
    RunNotFoundError,
    TrackingDependencyMissingError,
    TrackingUnavailableError,
)
from app.evaluation.catalog import CATALOG, PARAM_LABELS, CatalogMetric
from app.evaluation.results import RUN_ID_PATTERN, display_path, redact_paths
from app.schemas.evaluations import MetricValue
from app.schemas.experiments import (
    MetricDelta,
    ParamDiff,
    RunComparison,
    RunDetail,
    RunList,
    RunSummary,
    TrackingStatus,
)
from app.tracking.mlflow_tracking import TrackingConfig

if TYPE_CHECKING:
    from mlflow.entities import Run
    from mlflow.tracking import MlflowClient

logger = logging.getLogger(__name__)

MLFLOW_RUN_ID_PATTERN = r"^[0-9a-f]{32}$"
ARTIFACTS = {
    "report.json": "application/json",
    "report.md": "text/markdown; charset=utf-8",
    "failures.json": "application/json",
}
_MAX_RUNS = 500
_LATENCY_NOISE = 0.10  # relative latency changes below 10 % are reported as unchanged
_JUDGE_PARAMS = ("config.judge_enabled", "config.judge_model", "config.judge_prompt_version")
_TAGS = {
    "label": "ragguard.label",
    "ragguard_run_id": "ragguard.run_id",
    "rescored_from": "ragguard.rescored_from",
    "git_commit": "git_commit",
    "git_dirty": "git_dirty",
}


def local_store_path(tracking_uri: str) -> Path | None:
    """File behind a `sqlite:///` URI (relative paths as SQLAlchemy resolves them)."""
    prefix = "sqlite:///"
    if not tracking_uri.startswith(prefix):
        return None
    return Path(tracking_uri[len(prefix) :])


def describe_store(tracking_uri: str) -> str:
    """Store location safe to show in the browser: no credentials, no absolute paths."""
    path = local_store_path(tracking_uri)
    if path is not None:
        if path.resolve() == (REPO_ROOT / "mlflow.db").resolve():
            return "mlflow.db in the repository root (SQLite)"
        return f"{display_path(path)} (SQLite)"
    parsed = urlparse(tracking_uri)
    if parsed.hostname:
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{parsed.hostname}{port}"
    return f"{parsed.scheme or 'unknown'} store"


def _default_client(tracking_uri: str) -> MlflowClient:
    # Fail fast instead of MLflow's default retries with backoff (minutes) for HTTP stores.
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "0")
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "10")
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    os.environ.setdefault("MLFLOW_ENABLE_ARTIFACTS_PROGRESS_BAR", "false")
    try:
        from mlflow.tracking import MlflowClient
    except ImportError as exc:
        raise TrackingDependencyMissingError(
            "MLflow is not installed in the API environment. Install "
            "backend/requirements-eval.txt to read tracked runs."
        ) from exc
    return MlflowClient(tracking_uri=tracking_uri)


def _iso(ms: Any) -> str | None:
    if not isinstance(ms, int | float):
        return None
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="seconds")


def run_metric(spec: CatalogMetric, metrics: dict[str, float]) -> MetricValue:
    """A catalog metric from MLflow metrics (`key` and `key.denominator`)."""
    value = metrics.get(spec.key)
    denominator = metrics.get(f"{spec.key}.denominator")
    available = value is not None or denominator is not None
    numerator: float | None = None
    if spec.kind == "rate" and value is not None and denominator is not None:
        # Rates are counts / denominator, logged rounded to 4 decimals: the nearest
        # integer recovers the count exactly for denominators below 10,000.
        numerator = float(round(value * denominator))
    return MetricValue(
        key=spec.key,
        label=spec.label,
        group=spec.group,
        direction=spec.direction,
        kind=spec.kind,
        supplementary=spec.supplementary,
        available=available,
        value=value,
        numerator=numerator,
        denominator=int(denominator) if denominator is not None else None,
    )


def _assess(
    spec: CatalogMetric, base: MetricValue, cand: MetricValue, comparable: bool
) -> tuple[float | None, str]:
    if base.value is None or cand.value is None:
        return None, "unavailable"
    delta = cand.value - base.value
    if not comparable or (base.kind in ("rate", "mean") and base.denominator != cand.denominator):
        return delta, "not_comparable"
    if abs(delta) < 1e-9:
        return delta, "unchanged"
    if spec.kind == "ms" and base.value > 0 and abs(delta) / base.value < _LATENCY_NOISE:
        return delta, "unchanged"
    if spec.direction == "neutral":
        return delta, "changed"
    better = delta > 0 if spec.direction == "higher" else delta < 0
    return delta, "improved" if better else "regressed"


def compare_runs(baseline: RunSummary, candidate: RunSummary) -> RunComparison:
    """Side-by-side parameters and catalog metrics with explicit comparability notes."""
    bp, cp = baseline.params, candidate.params
    notes: list[str] = []
    comparable = True
    if baseline.run_id == candidate.run_id:
        notes.append("The same run is selected as baseline and candidate.")
    if bp.get("dataset.fingerprint_sha256") != cp.get("dataset.fingerprint_sha256"):
        comparable = False
        notes.append(
            "Different datasets (fingerprints differ): metric differences mix configuration "
            "and dataset changes, so no metric is marked improved or regressed."
        )
    if bp.get("dataset.cases_run") != cp.get("dataset.cases_run"):
        comparable = False
        notes.append(
            f"Different numbers of cases ({bp.get('dataset.cases_run')} vs "
            f"{cp.get('dataset.cases_run')}): rates are not comparable."
        )
    if bp.get("report.schema_version") != cp.get("report.schema_version"):
        notes.append(
            f"Report schemas differ ({bp.get('report.schema_version')} vs "
            f"{cp.get('report.schema_version')}): metrics introduced later are unavailable "
            "for the older run."
        )
    if bp.get("config.evaluator_version") != cp.get("config.evaluator_version"):
        notes.append(
            f"Evaluator versions differ ({bp.get('config.evaluator_version') or 'e1'} vs "
            f"{cp.get('config.evaluator_version') or 'e1'}): deterministic checks changed "
            "(D-068), so pass rates are not strictly comparable."
        )
    generation_keys = [k for k in PARAM_LABELS if k.startswith("config.") and "judge" not in k]
    if (
        comparable
        and baseline.run_id != candidate.run_id
        and all(bp.get(k) == cp.get(k) for k in generation_keys)
    ):
        notes.append(
            "Retrieval and generation settings are identical, so differences between these runs "
            "show run-to-run variation of the model, not the effect of a configuration change."
        )
    judge_comparable = all(bp.get(k) == cp.get(k) for k in _JUDGE_PARAMS) and (
        bp.get("config.judge_enabled") == "true"
    )
    if not judge_comparable:
        notes.append(
            "Judge settings differ or the judge was disabled: LLM-judge metrics are not compared."
        )
    notes.append(
        "Each value comes from a single run. Generation is not deterministic, so small "
        "differences can be run-to-run noise; latency changes under 10% are shown as unchanged."
    )
    params = [
        ParamDiff(
            key=key,
            label=label,
            baseline=bp.get(key),
            candidate=cp.get(key),
            changed=bp.get(key) != cp.get(key),
        )
        for key, label in PARAM_LABELS.items()
    ]
    base_metrics = {m.key: m for m in baseline.metrics}
    cand_metrics = {m.key: m for m in candidate.metrics}
    deltas: list[MetricDelta] = []
    for spec in CATALOG:
        base, cand = base_metrics[spec.key], cand_metrics[spec.key]
        ok = comparable and (judge_comparable or not spec.supplementary)
        delta, assessment = _assess(spec, base, cand, ok)
        deltas.append(
            MetricDelta(
                key=spec.key,
                label=spec.label,
                group=spec.group,
                supplementary=spec.supplementary,
                baseline=base,
                candidate=cand,
                delta=delta,
                assessment=assessment,  # type: ignore[arg-type]
            )
        )
    return RunComparison(
        baseline=baseline,
        candidate=candidate,
        comparable=comparable,
        notes=notes,
        params=params,
        metrics=deltas,
        improved=[d.label for d in deltas if d.assessment == "improved"],
        regressed=[d.label for d in deltas if d.assessment == "regressed"],
    )


class TrackingReader:
    """Read-only view of one MLflow experiment."""

    def __init__(
        self,
        config: TrackingConfig,
        results_dir: Path,
        client_factory: Callable[[str], MlflowClient] = _default_client,
    ) -> None:
        self.config = config
        self.results_dir = results_dir
        self._factory = client_factory
        self._client: MlflowClient | None = None
        self._lock = threading.Lock()

    @property
    def store(self) -> str:
        return describe_store(self.config.tracking_uri)

    def _store_missing(self) -> bool:
        path = local_store_path(self.config.tracking_uri)
        return path is not None and not path.is_file()

    def _get_client(self) -> MlflowClient:
        with self._lock:
            if self._client is None:
                self._client = self._factory(self.config.tracking_uri)
            return self._client

    def _status(self, state: str, detail: str, count: int | None = None) -> TrackingStatus:
        return TrackingStatus(
            state=state,  # type: ignore[arg-type]
            detail=detail,
            store=self.store,
            experiment_name=self.config.experiment_name,
            run_count=count,
        )

    def _search(self) -> list[Run] | None:
        """Runs of the experiment, newest first; None if the experiment does not exist."""
        client = self._get_client()
        experiment = client.get_experiment_by_name(self.config.experiment_name)
        if experiment is None:
            return None
        return list(
            client.search_runs(
                [experiment.experiment_id],
                max_results=_MAX_RUNS,
                order_by=["attributes.start_time DESC"],
            )
        )

    def list_runs(self) -> RunList:
        if self._store_missing():
            return RunList(
                tracking=self._status(
                    "no_store",
                    "The local tracking store does not exist yet. It is created by the first "
                    "evaluation run that is not started with --no-tracking.",
                ),
                runs=[],
            )
        try:
            runs = self._search()
        except TrackingDependencyMissingError as exc:
            return RunList(tracking=self._status("dependency_missing", exc.message), runs=[])
        except Exception as exc:
            logger.warning("Reading the MLflow store failed: %s", exc)
            return RunList(
                tracking=self._status(
                    "unavailable", f"The tracking store could not be read ({type(exc).__name__})."
                ),
                runs=[],
            )
        if runs is None:
            status = self._status(
                "empty",
                f"The experiment '{self.config.experiment_name}' does not exist in this store "
                "yet; the first tracked evaluation run creates it.",
                0,
            )
            return RunList(tracking=status, runs=[])
        summaries = [self._summary(run) for run in runs]
        state = "available" if summaries else "empty"
        detail = (
            f"{len(summaries)} run(s) in '{self.config.experiment_name}'."
            if summaries
            else f"The experiment '{self.config.experiment_name}' has no runs yet."
        )
        return RunList(tracking=self._status(state, detail, len(summaries)), runs=summaries)

    def status(self) -> TrackingStatus:
        return self.list_runs().tracking

    def _summary(self, run: Run) -> RunSummary:
        tags = run.data.tags
        params = {
            k: v
            for k, v in run.data.params.items()
            if k.startswith(("config.", "dataset.", "report."))
        }
        metrics = dict(run.data.metrics)
        ragguard_id = tags.get(_TAGS["ragguard_run_id"])
        local = False
        if ragguard_id and re.match(RUN_ID_PATTERN, ragguard_id):
            local = (self.results_dir / ragguard_id / "report.json").is_file()
        commit = tags.get(_TAGS["git_commit"])
        return RunSummary(
            run_id=run.info.run_id,
            run_name=run.info.run_name,
            status=run.info.status,
            start_time=_iso(run.info.start_time),
            end_time=_iso(run.info.end_time),
            label=tags.get(_TAGS["label"]),
            ragguard_run_id=ragguard_id,
            imported=tags.get("ragguard.imported") == "true",
            rescored_from=tags.get(_TAGS["rescored_from"]),
            git_commit=commit[:12] if commit else None,
            git_dirty=tags.get(_TAGS["git_dirty"]),
            local_report=local,
            params=params,
            metrics=[run_metric(spec, metrics) for spec in CATALOG],
        )

    def _run(self, run_id: str) -> Run:
        if self._store_missing():
            raise RunNotFoundError("The tracking store does not exist yet.")
        try:
            client = self._get_client()
            experiment = client.get_experiment_by_name(self.config.experiment_name)
            run = client.get_run(run_id) if experiment is not None else None
        except (TrackingDependencyMissingError, RunNotFoundError):
            raise
        except Exception as exc:
            if getattr(exc, "error_code", None) == "RESOURCE_DOES_NOT_EXIST":
                run = None
            else:
                logger.warning("Reading MLflow run %s failed: %s", run_id, exc)
                raise TrackingUnavailableError(
                    f"The tracking store could not be read ({type(exc).__name__})."
                ) from exc
        if run is None or experiment is None or run.info.experiment_id != experiment.experiment_id:
            raise RunNotFoundError(
                f"No run with ID '{run_id}' in experiment '{self.config.experiment_name}'."
            )
        return run

    def get_run(self, run_id: str) -> RunDetail:
        run = self._run(run_id)
        try:
            listed = self._get_client().list_artifacts(run_id, "reports")
        except Exception as exc:
            logger.warning("Listing artifacts of %s failed: %s", run_id, exc)
            listed = []
        names = {Path(a.path).name for a in listed if not a.is_dir}
        return RunDetail(
            run=self._summary(run),
            artifacts=[name for name in ARTIFACTS if name in names],
            all_metrics=dict(sorted(run.data.metrics.items())),
        )

    def compare(self, baseline_id: str, candidate_id: str) -> RunComparison:
        return compare_runs(
            self._summary(self._run(baseline_id)), self._summary(self._run(candidate_id))
        )

    def artifact(self, run_id: str, name: str) -> tuple[str, str]:
        """Text of one whitelisted report artifact, absolute paths redacted."""
        if name not in ARTIFACTS:
            raise ArtifactNotFoundError(f"'{name}' is not a downloadable artifact.")
        self._run(run_id)
        try:
            with tempfile.TemporaryDirectory(prefix="ragguard-artifact-") as tmp:
                local = self._get_client().download_artifacts(run_id, f"reports/{name}", tmp)
                text = Path(local).read_text(encoding="utf-8")
        except Exception as exc:
            logger.info("Artifact %s of %s not available: %s", name, run_id, exc)
            raise ArtifactNotFoundError(f"This run has no readable {name} artifact.") from exc
        return redact_paths(text), ARTIFACTS[name]
