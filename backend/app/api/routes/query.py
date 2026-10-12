"""Question-answering endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.dependencies import PipelineDep
from app.schemas.query import QueryRequest, QueryResponse

router = APIRouter(tags=["query"])


@router.post("/query", response_model=QueryResponse)
def query(pipeline: PipelineDep, request: QueryRequest) -> QueryResponse:
    return pipeline.answer(request)
