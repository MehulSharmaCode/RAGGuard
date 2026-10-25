"""Read-only access to saved evaluation reports. Never starts an evaluation."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Path
from fastapi.responses import Response

from app.api.dependencies import ReportsDep
from app.evaluation.results import RUN_ID_PATTERN
from app.schemas.evaluations import EvaluationDetail, EvaluationList

router = APIRouter(prefix="/evaluations", tags=["evaluations"])
RunId = Annotated[str, Path(pattern=RUN_ID_PATTERN, max_length=128)]


@router.get("", response_model=EvaluationList)
def list_evaluations(reports: ReportsDep) -> EvaluationList:
    return reports.list()


@router.get("/{run_id}", response_model=EvaluationDetail)
def get_evaluation(reports: ReportsDep, run_id: RunId) -> EvaluationDetail:
    return reports.detail(run_id)


@router.get("/{run_id}/files/{name}", response_class=Response)
def get_evaluation_file(
    reports: ReportsDep, run_id: RunId, name: Literal["report.json", "report.md"]
) -> Response:
    text, media_type = reports.file(run_id, name)
    return Response(
        content=text,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{run_id}-{name}"'},
    )
