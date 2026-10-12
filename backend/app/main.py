"""RAGGuard backend entry point: application factory, middleware, error handlers.

Run locally (from `backend/`):  .venv/bin/uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import documents, health, query
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.embeddings.sentence_transformer import SentenceTransformerEmbedder
from app.generation.factory import build_provider
from app.pipeline import RAGPipeline
from app.retrieval.vector_store import QdrantVectorStore

logger = logging.getLogger(__name__)


def build_pipeline(settings: Settings) -> RAGPipeline:
    return RAGPipeline(
        settings=settings,
        embedder=SentenceTransformerEmbedder(settings.embedding_model),
        vector_store=QdrantVectorStore.from_settings(settings),
        provider=build_provider(settings),
    )


def _error(status_code: int, code: str, message: str, **extra: object) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"error": {"code": code, "message": message, **extra}}
    )


def create_app(settings: Settings | None = None, pipeline: RAGPipeline | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.pipeline = pipeline or build_pipeline(settings)
        logger.info(
            "RAGGuard API started (provider=%s, qdrant=%s)",
            settings.generation_provider,
            "remote" if settings.qdrant_url else "local",
        )
        yield
        if pipeline is None:  # only close what this app created
            app.state.pipeline.vector_store.close()

    app = FastAPI(title="RAGGuard API", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return _error(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"location": list(e.get("loc", ())), "message": e.get("msg", "")} for e in exc.errors()
        ]
        return _error(422, "validation_error", "The request is invalid.", details=details)

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=exc)
        return _error(500, "internal_error", "An unexpected error occurred.")

    app.include_router(health.router)
    app.include_router(documents.router)
    app.include_router(query.router)
    return app


app = create_app()
