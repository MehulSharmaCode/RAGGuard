"""Read-only dashboard endpoints: saved evaluation reports, MLflow runs, system status.

Reports are produced by the real evaluation runner (fake embedder and model) into a
temporary results directory; MLflow runs are logged into a temporary SQLite store with
the production `log_report`. Nothing reads the repository's results or `mlflow.db`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from mlflow.tracking import MlflowClient

from app.core.config import Settings
from app.core.errors import TrackingDependencyMissingError
from app.evaluation.catalog import CATALOG
from app.evaluation.dataset import LoadedDataset, load_dataset
from app.evaluation.report import write_reports
from app.evaluation.results import case_findings, redact_paths
from app.evaluation.runner import RunOptions, run_evaluation
from app.generation.base import ProviderStatus
from app.main import build_tracking_reader, create_app
from app.pipeline import RAGPipeline
from app.schemas.evaluations import MetricValue
from app.schemas.experiments import RunSummary
from app.tracking.mlflow_tracking import TrackingConfig, log_report, resolve_config
from app.tracking.reader import TrackingReader, compare_runs, describe_store
from tests.conftest import FREEDONIA_TXT, FakeEmbedder, FakeProvider

SECRET = "sk-test-secret-value-123"


# --- fixtures ----------------------------------------------------------------------
def _write_dataset(root: Path, version: str = "1") -> LoadedDataset:
    (root / "corpus").mkdir(parents=True, exist_ok=True)
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
            "id": "ANS-002",
            "question": "What is the national currency of Freedonia?",
            "answerability": "answerable",
            "category": "factual",
            "reference_answer": "The Freedonian crown.",
            "expected_sources": ["freedonia.txt"],
            "required_facts": [{"description": "currency", "match_any": ["crown"]}],
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
        "dataset_id": "dashboard-test",
        "version": version,
        "description": "d",
        "corpus_dir": "corpus",
        "cases": cases,
    }
    (root / "dataset.json").write_text(json.dumps(data), encoding="utf-8")
    return load_dataset(root / "dataset.json")


def _run(dataset: LoadedDataset, settings: Settings, work: Path) -> dict[str, Any]:
    # The fake model always answers the capital question, so ANS-002 fails (missing fact).
    outcome = run_evaluation(
        dataset,
        settings=settings,
        embedder=FakeEmbedder(),
        provider=FakeProvider(),
        judge=None,
        options=RunOptions(work_dir=work),
    )
    json_path, _ = write_reports(outcome.report, settings.evaluation_results_dir)
    return dict(json.loads(json_path.read_text(encoding="utf-8")))


@pytest.fixture
def dataset(tmp_path: Path) -> LoadedDataset:
    return _write_dataset(tmp_path / "dataset")


@pytest.fixture
def saved_report(dataset: LoadedDataset, settings: Settings, tmp_path: Path) -> dict[str, Any]:
    return _run(dataset, settings, tmp_path / "work")


def _client(
    settings: Settings, pipeline: RAGPipeline, tracking: TrackingReader | None = None
) -> TestClient:
    return TestClient(create_app(settings, pipeline, tracking))


@pytest.fixture
def api(settings: Settings, pipeline: RAGPipeline) -> Iterator[TestClient]:
    with _client(settings, pipeline) as client:
        yield client


# --- evaluation reports ------------------------------------------------------------
def test_no_reports_is_an_empty_state_not_an_error(api: TestClient) -> None:
    response = api.get("/evaluations")
    assert response.status_code == 200
    assert response.json()["reports"] == []


def test_saved_report_is_listed_and_detail_matches_it(
    api: TestClient, saved_report: dict[str, Any]
) -> None:
    run_id = saved_report["run_id"]
    listing = api.get("/evaluations").json()
    (summary,) = listing["reports"]
    assert summary["run_id"] == run_id and summary["readable"] is True
    assert summary["schema_version"] == "2.0"
    assert summary["dataset_version"] == "1" and summary["cases_run"] == 3
    assert summary["params"]["config.min_retrieval_score"] == "0.3"
    assert "/" not in listing["results_dir"].split(" ")[0] or "outside" in listing["results_dir"]

    detail = api.get(f"/evaluations/{run_id}").json()
    agg = saved_report["aggregates"]
    metrics = {m["key"]: m for m in detail["metrics"]}
    assert set(metrics) == {m.key for m in CATALOG}
    pass_rate = metrics["correctness.case_pass_rate"]
    assert pass_rate["available"] is True
    assert pass_rate["value"] == agg["correctness"]["case_pass_rate"]["value"]
    assert (pass_rate["numerator"], pass_rate["denominator"]) == (2, 3)
    # judge disabled: present in the report with denominator 0 -> available, no value
    judge = metrics["judge.mean_correctness"]
    assert (judge["available"], judge["value"], judge["denominator"]) == (True, None, 0)
    # a real zero stays zero
    assert metrics["answerability.false_answer_rate"]["value"] == 0.0

    cases = {c["case_id"]: c for c in detail["cases"]}
    for raw in saved_report["cases"]:
        view = cases[raw["case_id"]]
        assert view["answer"] == raw["answer"]
        assert view["outcome"] == raw["outcome"]
        assert view["verdict"] == ("pass" if raw["correct"] else "fail")
        assert [p["filename"] for p in view["retrieved"]] == [
            p["filename"] for p in raw["retrieved"]
        ]
    failed = cases["ANS-002"]
    assert failed["verdict"] == "fail"
    assert failed["facts_missing"] == ["currency"]
    assert [f["kind"] for f in failed["findings"]] == ["missing_facts"]
    assert failed["reference_answer"] == "The Freedonian crown."
    assert cases["ANS-001"]["findings"] == []
    assert cases["UNA-UNR-001"]["outcome"] == "fallback"
    assert detail["metric_definitions"] and detail["limitations"]


def test_report_files_are_served_with_paths_redacted(
    api: TestClient, saved_report: dict[str, Any], settings: Settings
) -> None:
    run_id = saved_report["run_id"]
    response = api.get(f"/evaluations/{run_id}/files/report.md")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "attachment" in response.headers["content-disposition"]
    assert response.text.startswith(f"# RAGGuard evaluation report `{run_id}`")
    as_json = api.get(f"/evaluations/{run_id}/files/report.json")
    assert as_json.json()["run_id"] == run_id
    assert api.get(f"/evaluations/{run_id}/files/secrets.txt").status_code == 422


def test_redaction_of_repository_and_home_paths() -> None:
    from app.core.config import REPO_ROOT

    text = f'"{REPO_ROOT}/evaluation/datasets/dataset.json" {Path.home()}/notes'
    assert redact_paths(text) == '"evaluation/datasets/dataset.json" ~/notes'


def test_legacy_schema_metrics_are_unavailable_not_zero(
    api: TestClient, settings: Settings
) -> None:
    run_dir = settings.evaluation_results_dir / "20260101T000000Z-aaaaaa"
    run_dir.mkdir(parents=True)
    legacy = {
        "schema_version": "1.0",
        "run_id": "20260101T000000Z-aaaaaa",
        "started_at": "2026-01-01T00:00:00+00:00",
        "status": "completed",
        "dataset": {"version": "1.0.0", "cases_run": 1},
        "configuration": {"prompt_version": "v1"},
        "aggregates": {
            "answerability": {"false_answer_rate": {"value": 0.0, "numerator": 0, "denominator": 9}}
        },
        "cases": [
            {
                "case_id": "UNA-001",
                "question": "q",
                "category": "unrelated",
                "answerability": "unanswerable",
                "outcome": "answered",
                "answer": "made up",
                "retrieved": [],
            }
        ],
    }
    (run_dir / "report.json").write_text(json.dumps(legacy), encoding="utf-8")
    detail = api.get("/evaluations/20260101T000000Z-aaaaaa").json()
    metrics = {m["key"]: m for m in detail["metrics"]}
    assert metrics["correctness.case_pass_rate"]["available"] is False
    assert metrics["correctness.case_pass_rate"]["value"] is None
    assert metrics["security.attack_success_rate"]["available"] is False
    assert metrics["answerability.false_answer_rate"] == {
        **metrics["answerability.false_answer_rate"],
        "available": True,
        "value": 0.0,
        "denominator": 9,
    }
    (case,) = detail["cases"]
    assert case["verdict"] == "unscored"  # schema 1 has no deterministic verdict
    assert [f["kind"] for f in case["findings"]] == ["false_answer"]


def test_malformed_and_missing_reports_fail_safely(api: TestClient, settings: Settings) -> None:
    root = settings.evaluation_results_dir
    (root / "20260101T000000Z-bad000").mkdir(parents=True)
    (root / "20260101T000000Z-bad000" / "report.json").write_text("{not json", encoding="utf-8")
    (root / "20260101T000000Z-arr000").mkdir()
    (root / "20260101T000000Z-arr000" / "report.json").write_text("[1, 2]", encoding="utf-8")
    (root / "20260101T000000Z-none00").mkdir()
    (root / "notes.txt").write_text("not a run", encoding="utf-8")

    reports = {r["run_id"]: r for r in api.get("/evaluations").json()["reports"]}
    assert set(reports) == {
        "20260101T000000Z-bad000",
        "20260101T000000Z-arr000",
        "20260101T000000Z-none00",
    }
    assert reports["20260101T000000Z-bad000"]["problem"] == "report.json is not valid JSON."
    assert "does not look like" in reports["20260101T000000Z-arr000"]["problem"]
    assert reports["20260101T000000Z-none00"]["problem"] == "report.json is missing."
    assert all(r["readable"] is False and r["headline"] == [] for r in reports.values())

    bad = api.get("/evaluations/20260101T000000Z-bad000")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "report_unreadable"
    missing = api.get("/evaluations/20260101T000000Z-zzzzzz")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "report_not_found"


def test_run_ids_cannot_escape_the_results_directory(
    api: TestClient, settings: Settings, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "report.json").write_text(json.dumps({"run_id": "x"}), encoding="utf-8")
    settings.evaluation_results_dir.mkdir(parents=True, exist_ok=True)
    os.symlink(outside, settings.evaluation_results_dir / "linked-run")

    assert api.get("/evaluations").json()["reports"] == []  # symlinks are not listed
    assert api.get("/evaluations/linked-run").status_code == 404
    for path in ("/evaluations/..", "/evaluations/.hidden", "/evaluations/a%2F..%2Fb"):
        assert api.get(path).status_code in (404, 422), path
    assert api.get("/evaluations/linked-run/files/report.json").status_code == 404


def test_case_findings_cover_security_and_citation_problems() -> None:
    case = {
        "answerability": "answerable",
        "outcome": "answered",
        "facts": {"missing": ["limit"]},
        "unsupported_content": ["safety margin"],
        "attack": {"status": "succeeded", "reasons": ["canary in answer"], "canary_leaked": True},
        "citations": {"invalid_ids": ["S7"]},
        "superseded_citations": ["policy_2023.txt"],
        "citation_support": {"unsupported": ["fee"], "uncited": ["date"]},
        "retrieval": {"hit_at_k": False, "expected_sources": ["spec.txt"]},
        "judge": {"status": "scored", "verdict": {"unsupported_claims": True}},
    }
    kinds = [f.kind for f in case_findings(case)]
    assert kinds == [
        "missing_facts",
        "unsupported_content",
        "attack_succeeded",
        "canary_leak",
        "invalid_citation",
        "superseded_citation",
        "unsupported_citation",
        "uncited_fact",
        "retrieval_miss",
        "judge_flag",
    ]
    refusal = case_findings({"answerability": "answerable", "outcome": "fallback"})
    assert [f.kind for f in refusal] == ["false_refusal"]
    error = case_findings({"error": {"stage": "generation", "code": "timeout", "message": "m"}})
    assert [f.kind for f in error] == ["pipeline_error"]
    judge_error = case_findings({"judge": {"status": "error", "error": "malformed"}})
    assert [(f.kind, f.detail) for f in judge_error] == [("judge_error", "malformed")]


# --- MLflow runs -------------------------------------------------------------------
@pytest.fixture
def tracked(
    dataset: LoadedDataset, settings: Settings, tmp_path: Path, saved_report: dict[str, Any]
) -> tuple[TrackingConfig, list[str]]:
    """Two runs in the experiment of `settings`: the saved report and a 0.5 threshold run."""
    config = TrackingConfig(
        tracking_uri=f"sqlite:///{tmp_path / 'store' / 'mlflow.db'}",
        experiment_name=settings.mlflow_experiment_name,
        artifact_root=tmp_path / "store" / "artifacts",
    )
    (tmp_path / "store").mkdir()
    run_dir = settings.evaluation_results_dir / saved_report["run_id"]
    first = log_report(
        saved_report,
        [run_dir / "report.json", run_dir / "report.md"],
        config,
        tags={"ragguard.label": "baseline", "ragguard.source_report": str(run_dir)},
    )
    stricter = settings.model_copy(update={"min_retrieval_score": 0.5})
    second_report = _run(dataset, stricter, tmp_path / "work2")
    second_dir = settings.evaluation_results_dir / second_report["run_id"]
    second = log_report(
        second_report,
        [second_dir / "report.json"],
        config,
        tags={"ragguard.label": "threshold 0.5"},
    )
    return config, [first.run_id, second.run_id]


def _reader(config: TrackingConfig, settings: Settings) -> TrackingReader:
    return TrackingReader(config, settings.evaluation_results_dir)


def test_runs_match_the_mlflow_records(
    settings: Settings, pipeline: RAGPipeline, tracked: tuple[TrackingConfig, list[str]]
) -> None:
    config, (first, second) = tracked
    with _client(settings, pipeline, _reader(config, settings)) as api:
        body = api.get("/experiments/runs").json()
        assert body["tracking"]["state"] == "available"
        assert body["tracking"]["run_count"] == 2
        assert "outside the repository" in body["tracking"]["store"]
        runs = {r["run_id"]: r for r in body["runs"]}
        assert list(runs) == [second, first]  # newest first

        record = MlflowClient(tracking_uri=config.tracking_uri).get_run(first)
        summary = runs[first]
        assert summary["label"] == "baseline" and summary["local_report"] is True
        assert summary["params"] == record.data.params
        metric = {m["key"]: m for m in summary["metrics"]}["correctness.case_pass_rate"]
        assert metric["value"] == record.data.metrics["correctness.case_pass_rate"]
        assert (metric["numerator"], metric["denominator"]) == (2, 3)
        assert "ragguard.source_report" not in json.dumps(body)  # tag not whitelisted

        detail = api.get(f"/experiments/runs/{first}").json()
        assert detail["artifacts"] == ["report.json", "report.md", "failures.json"]
        assert detail["all_metrics"] == dict(sorted(record.data.metrics.items()))
        assert api.get(f"/experiments/runs/{second}").json()["artifacts"] == [
            "report.json",
            "failures.json",
        ]

        artifact = api.get(f"/experiments/runs/{first}/artifacts/report.json")
        assert artifact.status_code == 200
        assert artifact.json()["run_id"] == summary["ragguard_run_id"]
        failures = api.get(f"/experiments/runs/{first}/artifacts/failures.json").json()
        assert [row["case_id"] for row in failures] == ["ANS-002"]
        missing = api.get(f"/experiments/runs/{second}/artifacts/report.md")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "artifact_not_found"
        assert api.get(f"/experiments/runs/{first}/artifacts/model.pkl").status_code == 422


def test_comparison_reports_parameters_trade_offs_and_comparability(
    settings: Settings, pipeline: RAGPipeline, tracked: tuple[TrackingConfig, list[str]]
) -> None:
    config, (first, second) = tracked
    with _client(settings, pipeline, _reader(config, settings)) as api:
        body = api.get(f"/experiments/compare?baseline={first}&candidate={second}").json()
    assert body["comparable"] is True
    changed = {p["key"]: (p["baseline"], p["candidate"]) for p in body["params"] if p["changed"]}
    assert changed == {"config.min_retrieval_score": ("0.3", "0.5")}
    assert any("Judge settings differ or the judge was disabled" in n for n in body["notes"])
    judge = {m["key"]: m for m in body["metrics"]}["judge.mean_correctness"]
    assert judge["assessment"] == "unavailable"
    assert not any("run-to-run variation of the model" in n for n in body["notes"])


def _summary(run_id: str, fingerprint: str, values: dict[str, float | None]) -> RunSummary:
    metrics = []
    for spec in CATALOG:
        value = values.get(spec.key)
        metrics.append(
            MetricValue(
                key=spec.key,
                label=spec.label,
                group=spec.group,
                direction=spec.direction,
                kind=spec.kind,
                supplementary=spec.supplementary,
                available=spec.key in values,
                value=value,
                numerator=None,
                denominator=10 if spec.kind == "rate" and spec.key in values else None,
            )
        )
    return RunSummary(
        run_id=run_id,
        run_name=run_id,
        status="FINISHED",
        start_time=None,
        end_time=None,
        label=None,
        ragguard_run_id=None,
        imported=False,
        rescored_from=None,
        git_commit=None,
        git_dirty=None,
        local_report=False,
        params={
            "dataset.fingerprint_sha256": fingerprint,
            "dataset.cases_run": "10",
            "report.schema_version": "2.0",
        },
        metrics=metrics,
    )


def test_trade_offs_are_not_presented_as_unqualified_improvement() -> None:
    base = _summary(
        "a" * 32,
        "f1",
        {
            "correctness.answer_correct_rate": 0.6,
            "security.attack_success_rate": 0.1,
            "latency.query.median_ms": 1000.0,
        },
    )
    cand = _summary(
        "b" * 32,
        "f1",
        {
            "correctness.answer_correct_rate": 0.8,
            "security.attack_success_rate": 0.3,
            "latency.query.median_ms": 1050.0,
        },
    )
    result = compare_runs(base, cand)
    assert result.comparable is True
    assert any("run-to-run variation of the model" in n for n in result.notes)  # same settings
    assert result.improved == ["Correct answers (answerable cases)"]
    assert result.regressed == ["Attack success (cases)"]
    by_key = {m.key: m for m in result.metrics}
    assert by_key["latency.query.median_ms"].assessment == "unchanged"  # within 10 %
    assert by_key["correctness.case_pass_rate"].assessment == "unavailable"

    other_dataset = compare_runs(
        base, _summary("c" * 32, "f2", {"security.attack_success_rate": 0.0})
    )
    assert other_dataset.comparable is False
    assert other_dataset.improved == [] and other_dataset.regressed == []
    attack = {m.key: m for m in other_dataset.metrics}["security.attack_success_rate"]
    assert attack.assessment == "not_comparable" and attack.delta == pytest.approx(-0.1)


def test_missing_store_is_reported_and_never_created(api: TestClient, settings: Settings) -> None:
    body = api.get("/experiments/runs").json()
    assert body["tracking"]["state"] == "no_store"
    assert body["runs"] == []
    assert settings.mlflow_tracking_uri is not None
    assert not Path(settings.mlflow_tracking_uri.removeprefix("sqlite:///")).exists()
    response = api.get(f"/experiments/runs/{'a' * 32}")
    assert response.status_code == 404 and response.json()["error"]["code"] == "run_not_found"


def test_existing_store_without_the_experiment_is_empty(
    settings: Settings, pipeline: RAGPipeline, tracked: tuple[TrackingConfig, list[str]]
) -> None:
    config, _ = tracked
    other = TrackingConfig(tracking_uri=config.tracking_uri, experiment_name="does-not-exist")
    with _client(settings, pipeline, _reader(other, settings)) as api:
        body = api.get("/experiments/runs").json()
    assert body["tracking"]["state"] == "empty" and body["tracking"]["run_count"] == 0


def _broken(error: Exception) -> Any:
    def factory(uri: str) -> Any:
        raise error

    return factory


@pytest.mark.parametrize(
    ("error", "state", "code"),
    [
        (TrackingDependencyMissingError("MLflow is not installed."), "dependency_missing",
         "tracking_dependency_missing"),
        (RuntimeError("database is locked"), "unavailable", "tracking_unavailable"),
    ],
)  # fmt: skip
def test_tracking_failures_are_explicit_and_rag_keeps_working(
    settings: Settings, pipeline: RAGPipeline, error: Exception, state: str, code: str
) -> None:
    config = TrackingConfig(tracking_uri="http://127.0.0.1:9", experiment_name="x")
    reader = TrackingReader(config, settings.evaluation_results_dir, client_factory=_broken(error))
    with _client(settings, pipeline, reader) as api:
        body = api.get("/experiments/runs").json()
        assert body["tracking"]["state"] == state and body["runs"] == []
        assert body["tracking"]["run_count"] is None  # unknown, not zero
        assert "database is locked" not in json.dumps(body)  # raw errors are not echoed
        response = api.get(f"/experiments/runs/{'a' * 32}")
        assert response.status_code == 503 and response.json()["error"]["code"] == code
        status = api.get("/system/status").json()
        tracking = {c["id"]: c for c in status["components"]}["tracking"]
        assert tracking["state"] == "unavailable"
        # ordinary RAG endpoints do not depend on tracking
        assert (
            api.post(
                "/ingest", files={"file": ("f.txt", FREEDONIA_TXT.encode(), "text/plain")}
            ).status_code
            == 201
        )
        answer = api.post("/query", json={"question": "What is the capital of Freedonia?"})
        assert answer.status_code == 200 and answer.json()["status"] == "answered"


def test_invalid_run_ids_are_rejected(api: TestClient) -> None:
    for path in (
        "/experiments/runs/not-a-run",
        "/experiments/runs/..%2F..%2Fmlflow.db",
        "/experiments/compare?baseline=x&candidate=y",
    ):
        response = api.get(path)
        assert response.status_code in (404, 422), path


def test_store_descriptions_hide_credentials_and_absolute_paths() -> None:
    assert describe_store("http://user:pw@tracking.example:5000/path?q=1") == (
        "http://tracking.example:5000"
    )
    assert describe_store(resolve_config(None).tracking_uri) == (
        "mlflow.db in the repository root (SQLite)"
    )
    assert describe_store("sqlite:////private/tmp/x/other.db") == (
        "other.db (outside the repository) (SQLite)"
    )


# --- system status -----------------------------------------------------------------
def test_status_reflects_real_checks_and_pending_stages(
    settings: Settings, pipeline: RAGPipeline, provider: FakeProvider, dataset: LoadedDataset
) -> None:
    config = settings.model_copy(update={"evaluation_dataset_path": dataset.path})
    with _client(config, pipeline) as api:
        body = api.get("/system/status").json()
        states = {c["id"]: c["state"] for c in body["components"]}
        assert states == {
            "api": "healthy",
            "vector_store": "healthy",
            "embedding": "healthy",
            "generation": "healthy",
            "evaluation": "healthy",
            "tracking": "configured",  # store configured but not created yet
            "containers": "configured",  # packaging exists; this test process is on the host
            "ci": "not_implemented",
        }
        assert body["latest_evaluation"] is None and body["evaluation_report_count"] == 0
        assert body["tracking"]["state"] == "no_store"
        assert body["configuration"]["min_retrieval_score"] == 0.3

        provider.status = ProviderStatus("unavailable", "The Ollama service is not reachable.")
        down = {c["id"]: c for c in api.get("/system/status").json()["components"]}
        assert down["generation"]["state"] == "unavailable"
        assert "not reachable" in down["generation"]["detail"]
        assert down["vector_store"]["state"] == "healthy"  # other components unaffected
        assert down["api"]["state"] == "healthy"


def test_status_reports_the_container_runtime_only_when_the_image_says_so(
    settings: Settings, pipeline: RAGPipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Stage 6 (D-075): never "not implemented" any more, never "healthy" on the host.
    def containers() -> dict[str, str]:
        with _client(settings, pipeline) as api:
            found = {c["id"]: c for c in api.get("/system/status").json()["components"]}
            return found["containers"]

    monkeypatch.delenv("RAGGUARD_RUNTIME", raising=False)
    host = containers()
    assert host["state"] == "configured" and host["verified"] is False
    assert "directly on the host" in host["detail"]
    monkeypatch.setenv("RAGGUARD_RUNTIME", "docker")
    inside = containers()
    assert inside["state"] == "healthy" and "inside the Docker Compose" in inside["detail"]
    monkeypatch.setenv("RAGGUARD_RUNTIME", "something-else")
    assert containers()["state"] == "configured"


def test_status_marks_an_unloaded_embedding_model_as_configured_only(
    settings: Settings, pipeline: RAGPipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(FakeEmbedder, "is_loaded", property(lambda self: False))
    with _client(settings, pipeline) as api:
        embedding = {c["id"]: c for c in api.get("/system/status").json()["components"]}[
            "embedding"
        ]
    assert embedding["state"] == "configured" and embedding["verified"] is False


def test_status_reports_an_invalid_dataset_and_the_latest_report(
    settings: Settings,
    pipeline: RAGPipeline,
    saved_report: dict[str, Any],
    tmp_path: Path,
) -> None:
    broken = tmp_path / "broken" / "dataset.json"
    broken.parent.mkdir()
    broken.write_text("{}", encoding="utf-8")
    config = settings.model_copy(update={"evaluation_dataset_path": broken})
    with _client(config, pipeline) as api:
        body = api.get("/system/status").json()
    evaluation = {c["id"]: c for c in body["components"]}["evaluation"]
    assert evaluation["state"] == "unavailable"
    assert body["latest_evaluation"]["run_id"] == saved_report["run_id"]
    assert body["evaluation_report_count"] == 1


def test_diagnostic_endpoints_return_no_secrets_or_private_paths(
    settings: Settings, pipeline: RAGPipeline, saved_report: dict[str, Any]
) -> None:
    secret = settings.model_copy(update={"gemini_api_key": SECRET, "qdrant_api_key": SECRET})
    with _client(secret, pipeline, build_tracking_reader(secret)) as api:
        bodies = [
            api.get("/system/status").text,
            api.get("/evaluations").text,
            api.get(f"/evaluations/{saved_report['run_id']}").text,
            api.get("/experiments/runs").text,
        ]
    for body in bodies:
        assert SECRET not in body
        assert str(Path.home()) not in body
        assert str(settings.evaluation_results_dir) not in body
