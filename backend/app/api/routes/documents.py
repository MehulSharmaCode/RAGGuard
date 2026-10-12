"""Document ingestion, listing, and deletion endpoints.

Handlers are synchronous so FastAPI runs the blocking embedding and Qdrant work
in its thread pool instead of on the event loop.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, UploadFile

from app.api.dependencies import PipelineDep
from app.schemas.documents import DeleteDocumentResponse, DocumentListResponse, IngestResponse

router = APIRouter(tags=["documents"])


@router.post("/ingest", response_model=IngestResponse, status_code=201)
def ingest_document(
    pipeline: PipelineDep,
    file: Annotated[UploadFile, File(description="One PDF or UTF-8 TXT file.")],
) -> IngestResponse:
    # Read at most one byte past the limit: enough to detect an oversized file.
    content = file.file.read(pipeline.settings.max_upload_bytes + 1)
    return pipeline.ingest(file.filename, content)


@router.get("/documents", response_model=DocumentListResponse)
def list_documents(pipeline: PipelineDep) -> DocumentListResponse:
    return DocumentListResponse(documents=pipeline.list_documents())


@router.delete("/documents/{document_id}", response_model=DeleteDocumentResponse)
def delete_document(pipeline: PipelineDep, document_id: UUID) -> DeleteDocumentResponse:
    return pipeline.delete_document(str(document_id))
