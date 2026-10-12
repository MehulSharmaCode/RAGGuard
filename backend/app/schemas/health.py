"""Schemas for the health endpoint."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ComponentHealth(BaseModel):
    status: str
    detail: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    api: Literal["ok"]
    generation_ready: bool
    components: dict[str, ComponentHealth]
    config: dict[str, str | int | float | None]


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody
