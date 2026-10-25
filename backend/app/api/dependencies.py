"""FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request

from app.core.config import Settings
from app.evaluation.results import ReportStore
from app.pipeline import RAGPipeline
from app.tracking.reader import TrackingReader


def get_pipeline(request: Request) -> RAGPipeline:
    return cast(RAGPipeline, request.app.state.pipeline)


def get_settings_dep(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_reports(request: Request) -> ReportStore:
    return cast(ReportStore, request.app.state.reports)


def get_tracking(request: Request) -> TrackingReader:
    return cast(TrackingReader, request.app.state.tracking)


PipelineDep = Annotated[RAGPipeline, Depends(get_pipeline)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
ReportsDep = Annotated[ReportStore, Depends(get_reports)]
TrackingDep = Annotated[TrackingReader, Depends(get_tracking)]
