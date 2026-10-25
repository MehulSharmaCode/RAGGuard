"""System status for the Pipeline view (`GET /system/status`)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.evaluations import EvaluationSummary
from app.schemas.experiments import TrackingStatus

ComponentState = Literal["healthy", "configured", "unavailable", "not_implemented"]


class ComponentStatus(BaseModel):
    id: str
    label: str
    state: ComponentState = Field(
        description="healthy: verified by a check in this request; configured: settings exist "
        "but availability was not verified; unavailable: a check failed; not_implemented: the "
        "capability does not exist yet."
    )
    detail: str
    verified: bool = Field(description="A live check ran while answering this request.")


class SystemStatus(BaseModel):
    checked_at: str
    components: list[ComponentStatus]
    configuration: dict[str, str | int | float | None] = Field(
        description="The same non-secret settings that /health reports."
    )
    latest_evaluation: EvaluationSummary | None
    evaluation_report_count: int
    tracking: TrackingStatus
