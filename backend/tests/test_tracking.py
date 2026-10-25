"""MLflow tracking: experiment, parameters/metrics vs. the report, artifacts, failures,
disabling, secrets, legacy import, and independence of the API from MLflow.

Uses a temporary SQLite tracking store per module and fakes for every model call.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mlflow.tracking import MlflowClient

from app.core.config import Settings
from app.evaluation import run_evaluation as cli
from app.evaluation.dataset import LoadedDataset, load_dataset
from app.evaluation.report import write_reports
from app.evaluation.runner import RunOptions, run_evaluation
from app.evaluation.schemas import EvaluationReport
from app.main import create_app
from app.tracking.mlflow_tracking import (
    TrackingConfig,
    TrackingError,
    extract_metrics,
    extract_params,
    log_report,
)
from tests.conftest import FREEDONIA_TXT, FakeEmbedder, FakeProvider

SECRET = "sk-test-secret-value-123"


@pytest.fixture(scope="module")
def tracking_uri(tmp_path_factory: pytest.TempPathFactory) -> str:
    return f"sqlite:///{tmp_path_factory.mktemp('mlflow') / 'mlflow.db'}"


@pytest.fixture(autouse=True)
def _temporary_artifact_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """CLI runs create experiments; keep their artifacts out of the repository's mlartifacts/."""
    original = cli.resolve_config

    def resolve(uri: str | None, name: str | None = None) -> TrackingConfig:
        return replace(original(uri, name), artifact_root=tmp_path / "cli-artifacts")

    monkeypatch.setattr(cli, "resolve_config", resolve)


def _config(uri: str, tmp: Path, name: str) -> TrackingConfig:
    return TrackingConfig(tracking_uri=uri, experiment_name=name, artifact_root=tmp / "artifacts")


@pytest.fixture
def dataset(tmp_path: Path) -> LoadedDataset:
    root = tmp_path / "dataset"
    (root / "corpus").mkdir(parents=True)
    (root / "corpus" / "freedonia.txt").write_text(FREEDONIA_TXT, encoding="utf-8")
    cases = [
        {
            "id": "ANS-001",
            "question": "What is the capital of Freedonia?",
            "answerability": "answerable",
            "category": "factual",
            "reference_answer": "Fredville.",
            "expected_sources": ["freedonia.txt"],
            "required_facts": [{"description": "capital", "match_any": ["Fredville"]}],
            "notes": "n",
        },
        {
            "id": "UNA-UNR-001",
            "question": "Give me a banana bread recipe",
            "answerability": "unanswerable",
            "category": "unrelated",
            "reference_answer": None,
            "expected_sources": [],
            "required_facts": [],
            "notes": "n",
        },
    ]
    data = {
        "dataset_id": "tracking-test",
        "version": "1",
        "description": "d",
        "corpus_dir": "corpus",
        "cases": cases,
    }
    (root / "dataset.json").write_text(json.dumps(data), encoding="utf-8")
    return load_dataset(root / "dataset.json")


@pytest.fixture
def secret_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={"gemini_api_key": SECRET, "qdrant_api_key": SECRET, "mlflow_tracking_uri": None}
    )


def _report(
    dataset: LoadedDataset, settings: Settings, tmp_path: Path
) -> tuple[EvaluationReport, list[Path]]:
    outcome = run_evaluation(
        dataset,
        settings=settings,
        embedder=FakeEmbedder(),
        provider=FakeProvider(),
        judge=None,
        options=RunOptions(work_dir=tmp_path / "work"),
    )
    paths = write_reports(outcome.report, tmp_path / "results")
    return outcome.report, list(paths)


def test_run_is_logged_with_matching_params_metrics_and_artifacts(
    dataset: LoadedDataset, secret_settings: Settings, tmp_path: Path, tracking_uri: str
) -> None:
    report, paths = _report(dataset, secret_settings, tmp_path)
    data = report.model_dump(mode="json")
    tracked = log_report(
        data,
        paths,
        _config(tracking_uri, tmp_path, "exp-match"),
        tags={"ragguard.label": "unit"},
    )
    client = MlflowClient(tracking_uri=tracking_uri)
    experiment = client.get_experiment_by_name("exp-match")
    assert experiment is not None and tracked.experiment_id == experiment.experiment_id
    run = client.get_run(tracked.run_id)
    assert run.info.status == "FINISHED"
    assert run.info.experiment_id == experiment.experiment_id

    # Parameters and metrics are exactly what the report says.
    assert run.data.params == extract_params(data)
    assert run.data.params["dataset.fingerprint_sha256"] == dataset.fingerprint
    assert run.data.params["config.min_retrieval_score"] == str(secret_settings.min_retrieval_score)
    assert run.data.params["config.judge_enabled"] == "false"
    logged = {k: v for k, v in run.data.metrics.items() if not k.startswith("threshold_sweep.")}
    assert logged == extract_metrics(data)
    agg = report.aggregates
    assert agg is not None
    assert logged["correctness.case_pass_rate"] == agg.correctness.case_pass_rate.value
    assert logged["correctness.case_pass_rate.denominator"] == 2
    assert logged["answerability.confusion.tp"] == agg.answerability.confusion.tp
    assert logged["latency.query.count"] == agg.latency.query.count
    assert "security.attack_success_rate" not in logged  # null rate omitted, not logged as 0
    assert logged["security.attack_success_rate.denominator"] == 0
    assert run.data.tags["ragguard.run_id"] == report.run_id
    assert run.data.tags["ragguard.status"] == report.status
    assert run.data.tags["ragguard.label"] == "unit"

    names = {a.path for a in client.list_artifacts(tracked.run_id, "reports")}
    assert names == {"reports/report.json", "reports/report.md", "reports/failures.json"}
    downloaded = Path(
        client.download_artifacts(tracked.run_id, "reports/report.json", str(tmp_path))
    )
    assert downloaded.read_text() == paths[0].read_text()

    # The threshold sweep is logged as a stepped series (step = threshold * 100).
    history = client.get_metric_history(tracked.run_id, "threshold_sweep.false_answer_rate")
    assert sorted(m.step for m in history) == [
        round(p.threshold * 100)
        for p in report.threshold_analysis.points  # type: ignore[union-attr]
    ]


def test_no_secrets_reach_mlflow(
    dataset: LoadedDataset, secret_settings: Settings, tmp_path: Path, tracking_uri: str
) -> None:
    report, paths = _report(dataset, secret_settings, tmp_path)
    data = report.model_dump(mode="json")
    data["configuration"]["gemini_api_key"] = SECRET  # even if a report carried one
    tracked = log_report(data, paths, _config(tracking_uri, tmp_path, "exp-secrets"))
    client = MlflowClient(tracking_uri=tracking_uri)
    run = client.get_run(tracked.run_id)
    blob = json.dumps(
        {"params": run.data.params, "tags": run.data.tags, "metrics": list(run.data.metrics)}
    )
    assert SECRET not in blob
    assert not any("key" in name.lower() for name in run.data.params)
    out = tmp_path / "dl"
    out.mkdir()
    for artifact in client.list_artifacts(tracked.run_id, "reports"):
        local = Path(client.download_artifacts(tracked.run_id, artifact.path, str(out)))
        assert SECRET not in local.read_text()


def test_tracking_failures_raise_and_mark_the_run_failed(
    dataset: LoadedDataset, settings: Settings, tmp_path: Path, tracking_uri: str
) -> None:
    report, paths = _report(dataset, settings, tmp_path)
    data = report.model_dump(mode="json")

    def unreachable(uri: str) -> MlflowClient:
        raise ConnectionError("tracking server down")

    with pytest.raises(TrackingError, match="tracking server down"):
        log_report(
            data, paths, _config(tracking_uri, tmp_path, "exp-x"), client_factory=unreachable
        )

    class BrokenMetrics(MlflowClient):
        def log_metric(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
            raise RuntimeError("disk full")

    with pytest.raises(TrackingError, match="disk full"):
        log_report(
            data,
            paths,
            _config(tracking_uri, tmp_path, "exp-broken"),
            client_factory=lambda uri: BrokenMetrics(tracking_uri=uri),
        )
    client = MlflowClient(tracking_uri=tracking_uri)
    experiment = client.get_experiment_by_name("exp-broken")
    assert experiment is not None
    runs = client.search_runs([experiment.experiment_id])
    assert [r.info.status for r in runs] == ["FAILED"]


def test_null_metrics_and_unknown_fields_are_not_logged() -> None:
    report = {
        "schema_version": "1.0",
        "configuration": {"generation_model": "m", "top_k": 4, "secret_token": "x"},
        "dataset": {"dataset_id": "d", "fingerprint_sha256": "abc"},
        "aggregates": {
            "retrieval": {"hit_rate_at_k": {"value": None, "numerator": 0, "denominator": 0}},
            "judge": {"enabled": False, "errors": ["A"]},
        },
    }
    assert extract_params(report) == {
        "config.generation_model": "m",
        "config.top_k": "4",
        "dataset.dataset_id": "d",
        "dataset.fingerprint_sha256": "abc",
        "report.schema_version": "1.0",
    }
    assert extract_metrics(report) == {
        "retrieval.hit_rate_at_k.denominator": 0.0,
        "judge.enabled": 0.0,
    }


# --- CLI -------------------------------------------------------------------------
@pytest.fixture
def fake_cli(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> Settings:
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "SentenceTransformerEmbedder", lambda name: FakeEmbedder())
    monkeypatch.setattr(cli, "build_provider", lambda s: FakeProvider())
    return settings


def _cli_args(dataset: LoadedDataset, tmp_path: Path, uri: str, *extra: str) -> list[str]:
    return [
        "--dataset",
        str(dataset.path),
        "--output-dir",
        str(tmp_path / "out"),
        "--work-dir",
        str(tmp_path / "work"),
        "--skip-judge",
        "--tracking-uri",
        uri,
        *extra,
    ]


def test_cli_logs_to_the_named_experiment(
    fake_cli: Settings, dataset: LoadedDataset, tmp_path: Path, tracking_uri: str
) -> None:
    code = cli.main(
        _cli_args(dataset, tmp_path, tracking_uri, "--experiment", "cli-exp", "--label", "pre-fix")
    )
    assert code == 0
    client = MlflowClient(tracking_uri=tracking_uri)
    experiment = client.get_experiment_by_name("cli-exp")
    assert experiment is not None
    (run,) = client.search_runs([experiment.experiment_id])
    assert run.data.tags["ragguard.label"] == "pre-fix"
    assert run.data.tags["git_commit"]
    assert run.data.tags["git_dirty"] in {"true", "false", "unknown"}


def test_cli_no_tracking_creates_no_store(
    fake_cli: Settings, dataset: LoadedDataset, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "never.db"
    assert cli.main(_cli_args(dataset, tmp_path, f"sqlite:///{db}", "--no-tracking")) == 0
    assert not db.exists()
    assert "tracking disabled" in capsys.readouterr().out


def test_cli_reports_tracking_failure_with_exit_code_3(
    fake_cli: Settings,
    dataset: LoadedDataset,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise TrackingError("MLflow tracking failed (x): boom")

    monkeypatch.setattr(cli, "log_report", fail)
    assert cli.main(_cli_args(dataset, tmp_path, "sqlite:///unused.db")) == 3
    captured = capsys.readouterr()
    assert "boom" in captured.err
    assert list((tmp_path / "out").glob("*/report.json")), "reports are still written"


def test_cli_imports_a_legacy_report(fake_cli: Settings, tmp_path: Path, tracking_uri: str) -> None:
    legacy = tmp_path / "legacy" / "report.json"
    legacy.parent.mkdir()
    legacy.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "run_id": "20261014T105939Z-59a6a7",
                "status": "completed",
                "started_at": "2026-10-14T10:59:39+00:00",
                "configuration": {"generation_model": "qwen3.5:9b", "top_k": 4},
                "dataset": {"dataset_id": "ragguard-synthetic", "version": "1.0.0"},
                "aggregates": {
                    "facts": {
                        "required_fact_recall": {"value": 1.0, "numerator": 25, "denominator": 25}
                    }
                },
            }
        )
    )
    code = cli.main(
        ["--import-report", str(legacy), "--tracking-uri", tracking_uri, "--experiment", "legacy"]
    )
    assert code == 0
    client = MlflowClient(tracking_uri=tracking_uri)
    experiment = client.get_experiment_by_name("legacy")
    assert experiment is not None
    (run,) = client.search_runs([experiment.experiment_id])
    assert run.data.tags["ragguard.imported"] == "true"
    assert run.data.tags["ragguard.run_id"] == "20261014T105939Z-59a6a7"
    assert run.data.metrics["facts.required_fact_recall"] == 1.0
    assert run.data.params["report.schema_version"] == "1.0"


# --- independence of the application from MLflow ----------------------------------
def test_api_does_not_import_mlflow() -> None:
    code = (
        "import sys; import app.main, app.pipeline, app.evaluation.runner; "
        "print('mlflow' in sys.modules)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        check=True,
    )
    assert out.stdout.strip() == "False"


def test_api_works_with_an_unusable_tracking_uri(settings: Settings, pipeline: Any) -> None:
    broken = settings.model_copy(update={"mlflow_tracking_uri": "http://127.0.0.1:9/nowhere"})
    with TestClient(create_app(broken, pipeline)) as client:
        assert client.get("/health").status_code == 200
        assert (
            client.post(
                "/ingest", files={"file": ("f.txt", FREEDONIA_TXT.encode(), "text/plain")}
            ).status_code
            == 201
        )
        response = client.post("/query", json={"question": "What is the capital of Freedonia?"})
        assert response.status_code == 200 and response.json()["status"] == "answered"
