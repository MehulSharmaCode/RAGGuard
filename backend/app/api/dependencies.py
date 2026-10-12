"""FastAPI dependencies."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request

from app.pipeline import RAGPipeline


def get_pipeline(request: Request) -> RAGPipeline:
    return cast(RAGPipeline, request.app.state.pipeline)


PipelineDep = Annotated[RAGPipeline, Depends(get_pipeline)]
