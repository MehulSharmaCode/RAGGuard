"""Health endpoint. Always 200 while the API is up; component readiness is in the body.
Never makes a generation call."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.dependencies import PipelineDep
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(pipeline: PipelineDep) -> HealthResponse:
    return pipeline.health()
