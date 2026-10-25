"""Component status for the Pipeline view, from real checks only.

Reuses the pipeline's health check (vector store, embedding model, generation
provider) and adds the evaluation dataset, saved reports, and the MLflow store.
Capabilities that do not exist yet are listed as `not_implemented`, never as healthy.
"""

from __future__ import annotations

import os
import threading
from datetime import UTC, datetime
from pathlib import Path

from app.evaluation.dataset import DatasetValidationError, load_dataset
from app.evaluation.results import ReportStore
from app.pipeline import RAGPipeline
from app.schemas.experiments import TrackingStatus
from app.schemas.system import ComponentStatus, SystemStatus
from app.tracking.reader import TrackingReader

_dataset_lock = threading.Lock()
_dataset_cache: dict[Path, tuple[tuple[int, int], ComponentStatus]] = {}


def _component(
    id_: str, label: str, state: str, detail: str, verified: bool = True
) -> ComponentStatus:
    return ComponentStatus(id=id_, label=label, state=state, detail=detail, verified=verified)  # type: ignore[arg-type]


# Set by deployment/backend.Dockerfile; the only signal that this process runs in the
# Docker Compose deployment (Stage 6, D-075). Nothing is inferred from the file system.
RUNTIME_ENV = "RAGGUARD_RUNTIME"


def containers_component() -> ComponentStatus:
    label = "Docker / Docker Compose"
    if os.environ.get(RUNTIME_ENV) == "docker":
        return _component(
            "containers",
            label,
            "healthy",
            "This API process runs inside the Docker Compose deployment (deployment/README.md).",
        )
    return _component(
        "containers",
        label,
        "configured",
        "A Docker Compose deployment is provided (compose.yaml, deployment/), but this API "
        "process runs directly on the host, not in a container.",
        verified=False,
    )


def dataset_component(path: Path) -> ComponentStatus:
    """Validate the evaluation dataset (cached until the dataset or corpus changes)."""
    label = "Evaluation dataset"
    if not path.is_file():
        return _component("evaluation", label, "unavailable", "The dataset file was not found.")
    corpus = path.parent / "corpus"
    stamp = (path.stat().st_mtime_ns, corpus.stat().st_mtime_ns if corpus.is_dir() else 0)
    with _dataset_lock:
        cached = _dataset_cache.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        loaded = load_dataset(path)
        status = _component(
            "evaluation",
            label,
            "healthy",
            f"{loaded.dataset.dataset_id} v{loaded.dataset.version}: "
            f"{len(loaded.dataset.cases)} cases, {len(loaded.corpus)} corpus files, validated. "
            "Evaluations run offline from the CLI, never per query.",
        )
    except DatasetValidationError as exc:
        status = _component(
            "evaluation",
            label,
            "unavailable",
            f"The dataset failed validation ({len(exc.problems)} problem(s)); run the CLI "
            "with --validate-only for details.",
        )
    with _dataset_lock:
        _dataset_cache[path] = (stamp, status)
    return status


def tracking_component(status: TrackingStatus) -> ComponentStatus:
    label = "Experiment tracking (MLflow)"
    detail = f"{status.detail} Store: {status.store}."
    if status.state == "available":
        return _component("tracking", label, "healthy", detail)
    if status.state in ("empty", "no_store"):
        return _component("tracking", label, "configured", detail)
    return _component("tracking", label, "unavailable", status.detail)


def build_status(
    pipeline: RAGPipeline, reports: ReportStore, tracking: TrackingReader, dataset_path: Path
) -> SystemStatus:
    health = pipeline.health()
    comps = health.components
    components = [_component("api", "Backend API", "healthy", "Responded to this request.")]

    store = comps["vector_store"]
    components.append(
        _component(
            "vector_store",
            "Vector store (Qdrant)",
            "healthy" if store.status == "ok" else "unavailable",
            store.detail,
        )
    )
    embedding = comps["embedding"]
    model = health.config.get("embedding_model")
    if embedding.status == "loaded":
        components.append(
            _component(
                "embedding",
                "Embedding model",
                "healthy",
                f"{model} is loaded in memory (used by an ingest or query since the API started).",
            )
        )
    else:
        components.append(
            _component(
                "embedding",
                "Embedding model",
                "configured",
                f"{model} is configured and loads on the first ingest or query; its availability "
                "has not been verified since the API started.",
                verified=False,
            )
        )
    generation = comps["generation"]
    gen_state = {"ready": "healthy", "configured": "configured"}.get(
        generation.status, "unavailable"
    )
    config = health.config
    provider = f"{config.get('generation_provider')} · {config.get('generation_model')}"
    components.append(
        _component(
            "generation",
            "Answer generation",
            gen_state,
            f"{provider}: {generation.detail}",
            verified=gen_state != "configured",
        )
    )
    components.append(dataset_component(dataset_path))

    listing = reports.list()
    readable = [r for r in listing.reports if r.readable]
    tracked = tracking.list_runs().tracking
    components.append(tracking_component(tracked))
    components.append(containers_component())
    components.append(
        _component(
            "ci",
            "CI tests and quality gate (GitHub Actions)",
            "configured",
            "GitHub Actions workflow ragguard-ci.yml (checks, offline quality gate, image "
            "build; nothing is pushed or deployed). The API does not query GitHub: recent "
            "runs are listed below, read by the browser from GitHub's public API.",
            verified=False,
        )
    )
    return SystemStatus(
        checked_at=datetime.now(UTC).isoformat(timespec="seconds"),
        components=components,
        configuration=health.config,
        latest_evaluation=readable[0] if readable else None,
        evaluation_report_count=len(readable),
        tracking=tracked,
    )
