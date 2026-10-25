"""Read-only views of MLflow evaluation runs (`GET /experiments...`)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.evaluations import MetricValue

TrackingState = Literal["available", "empty", "no_store", "dependency_missing", "unavailable"]


class TrackingStatus(BaseModel):
    state: TrackingState = Field(
        description="available: runs found; empty: store readable, no runs in the experiment; "
        "no_store: the local store file does not exist yet; dependency_missing: MLflow is not "
        "installed in the API environment; unavailable: the store could not be read."
    )
    detail: str
    store: str = Field(description="Store location without credentials or absolute paths.")
    experiment_name: str
    run_count: int | None


class RunSummary(BaseModel):
    run_id: str
    run_name: str | None
    status: str
    start_time: str | None
    end_time: str | None
    label: str | None
    ragguard_run_id: str | None
    imported: bool = Field(description="Logged later from an existing report (--import-report).")
    rescored_from: str | None
    git_commit: str | None
    git_dirty: str | None
    local_report: bool = Field(description="The matching report exists in EVALUATION_RESULTS_DIR.")
    params: dict[str, str]
    metrics: list[MetricValue]


class RunList(BaseModel):
    tracking: TrackingStatus
    runs: list[RunSummary] = Field(description="Newest first.")


class RunDetail(BaseModel):
    run: RunSummary
    artifacts: list[str] = Field(description="Downloadable report artifacts of this run.")
    all_metrics: dict[str, float] = Field(description="Every metric logged for the run.")


Assessment = Literal[
    "improved", "regressed", "unchanged", "changed", "not_comparable", "unavailable"
]


class ParamDiff(BaseModel):
    key: str
    label: str
    baseline: str | None
    candidate: str | None
    changed: bool


class MetricDelta(BaseModel):
    key: str
    label: str
    group: str
    supplementary: bool
    baseline: MetricValue
    candidate: MetricValue
    delta: float | None = Field(description="candidate - baseline, when both values exist.")
    assessment: Assessment


class RunComparison(BaseModel):
    baseline: RunSummary
    candidate: RunSummary
    comparable: bool = Field(description="Same dataset fingerprint, case count, and schema.")
    notes: list[str]
    params: list[ParamDiff]
    metrics: list[MetricDelta]
    improved: list[str] = Field(description="Labels of metrics that improved.")
    regressed: list[str] = Field(description="Labels of metrics that got worse.")
