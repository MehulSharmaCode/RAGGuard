"""Read-only access to MLflow evaluation runs (no writes, deletions, or registry)."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query
from fastapi.responses import Response

from app.api.dependencies import TrackingDep
from app.schemas.experiments import RunComparison, RunDetail, RunList
from app.tracking.reader import MLFLOW_RUN_ID_PATTERN

router = APIRouter(prefix="/experiments", tags=["experiments"])
RunId = Annotated[str, Path(pattern=MLFLOW_RUN_ID_PATTERN)]


@router.get("/runs", response_model=RunList)
def list_runs(tracking: TrackingDep) -> RunList:
    return tracking.list_runs()


@router.get("/runs/{run_id}", response_model=RunDetail)
def get_run(tracking: TrackingDep, run_id: RunId) -> RunDetail:
    return tracking.get_run(run_id)


@router.get("/compare", response_model=RunComparison)
def compare_runs(
    tracking: TrackingDep,
    baseline: Annotated[str, Query(pattern=MLFLOW_RUN_ID_PATTERN)],
    candidate: Annotated[str, Query(pattern=MLFLOW_RUN_ID_PATTERN)],
) -> RunComparison:
    return tracking.compare(baseline, candidate)


@router.get("/runs/{run_id}/artifacts/{name}", response_class=Response)
def get_artifact(
    tracking: TrackingDep,
    run_id: RunId,
    name: Literal["report.json", "report.md", "failures.json"],
) -> Response:
    text, media_type = tracking.artifact(run_id, name)
    return Response(
        content=text,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{run_id[:8]}-{name}"'},
    )
