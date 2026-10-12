"""Schemas for document ingestion, listing, and deletion."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class IngestResponse(BaseModel):
    document_id: str
    filename: str
    file_type: Literal["pdf", "txt"]
    total_pages: int | None
    pages_with_text: int
    chunk_count: int
    status: Literal["indexed"]
    ingested_at: str


class DocumentInfo(BaseModel):
    document_id: str
    filename: str
    file_type: str
    total_pages: int | None
    chunk_count: int
    status: Literal["indexed"]
    ingested_at: str


class DocumentListResponse(BaseModel):
    documents: list[DocumentInfo]


class DeleteDocumentResponse(BaseModel):
    document_id: str
    deleted_chunks: int
    status: Literal["deleted"]
