"""Component status for the Pipeline view, from real checks (never a generation call)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.dependencies import PipelineDep, ReportsDep, SettingsDep, TrackingDep
from app.schemas.system import SystemStatus
from app.system_status import build_status

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status", response_model=SystemStatus)
def system_status(
    pipeline: PipelineDep, reports: ReportsDep, tracking: TrackingDep, settings: SettingsDep
) -> SystemStatus:
    return build_status(pipeline, reports, tracking, settings.evaluation_dataset_path)
