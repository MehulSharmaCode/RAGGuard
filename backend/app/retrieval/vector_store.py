"""Qdrant storage and similarity search for document chunks.

One point per chunk. Vectors are L2-normalized and the collection uses COSINE
distance, so Qdrant scores are cosine similarities in [-1, 1] (higher is closer).

Client mode: remote server when `QDRANT_URL` is set, otherwise the embedded
client in persistent local mode at `QDRANT_LOCAL_PATH`. Never both.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, TypeVar

from qdrant_client import QdrantClient, models

from app.core.config import Settings
from app.core.errors import ConfigurationError, VectorStoreError
from app.ingestion.chunking import Chunk

logger = logging.getLogger(__name__)

DISTANCE = models.Distance.COSINE
_POINT_NAMESPACE = uuid.UUID("6f2b8f0e-6c55-4d1e-9a51-6b8c2c7f1a10")
_SCROLL_PAGE = 256

T = TypeVar("T")


@dataclass(frozen=True)
class DocumentRecord:
    document_id: str
    filename: str
    file_type: str
    total_pages: int | None
    ingested_at: str
    embedding_model: str


@dataclass(frozen=True)
class RetrievedChunk:
    point_id: str
    score: float
    document_id: str
    filename: str
    page_number: int | None
    chunk_index: int
    text: str
    char_start: int | None
    char_end: int | None


@dataclass(frozen=True)
class DocumentSummary:
    document_id: str
    filename: str
    file_type: str
    total_pages: int | None
    chunk_count: int
    ingested_at: str


def point_id_for(document_id: str, chunk_index: int) -> str:
    """Deterministic, globally unique point ID for a chunk of a document."""
    return str(uuid.uuid5(_POINT_NAMESPACE, f"{document_id}:{chunk_index}"))


def create_qdrant_client(settings: Settings) -> QdrantClient:
    if settings.qdrant_url:
        api_key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
        return QdrantClient(url=settings.qdrant_url, api_key=api_key, timeout=10)
    settings.qdrant_local_path.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(settings.qdrant_local_path))


def _document_filter(document_ids: list[str]) -> models.Filter:
    return models.Filter(
        must=[models.FieldCondition(key="document_id", match=models.MatchAny(any=document_ids))]
    )


class QdrantVectorStore:
    """Collection management, upsert, search, listing, and deletion.

    The client is created lazily by `client_factory` so the API can start even
    when storage is unavailable; failures surface as VectorStoreError.
    """

    def __init__(
        self,
        client_factory: Callable[[], QdrantClient],
        collection_name: str,
        *,
        is_local: bool,
    ) -> None:
        self.collection_name = collection_name
        self.is_local = is_local
        self._client_factory = client_factory
        self._client: QdrantClient | None = None
        self._validated_dimension: int | None = None
        # The embedded local client is not designed for concurrent access.
        self._lock = threading.RLock()

    @classmethod
    def from_settings(cls, settings: Settings) -> QdrantVectorStore:
        return cls(
            lambda: create_qdrant_client(settings),
            settings.qdrant_collection_name,
            is_local=not settings.qdrant_url,
        )

    # --- internals -------------------------------------------------------------
    @contextmanager
    def _guard(self) -> Iterator[None]:
        if self.is_local:
            with self._lock:
                yield
        else:
            yield

    def _run(self, action: str, operation: Callable[[QdrantClient], T]) -> T:
        with self._guard():
            try:
                if self._client is None:
                    self._client = self._client_factory()
                return operation(self._client)
            except (VectorStoreError, ConfigurationError):
                raise
            except Exception as exc:
                logger.exception("Qdrant %s failed", action)
                raise VectorStoreError(
                    f"The vector store is unavailable ({action} failed)."
                ) from exc

    def _collection_exists(self, client: QdrantClient) -> bool:
        return client.collection_exists(self.collection_name)

    def _check_dimension(self, client: QdrantClient, dimension: int) -> None:
        if self._validated_dimension == dimension:
            return
        info = client.get_collection(self.collection_name)
        params = info.config.params.vectors
        if not isinstance(params, models.VectorParams):
            raise ConfigurationError(
                "The Qdrant collection uses named vectors and is incompatible with RAGGuard."
            )
        if params.size != dimension or params.distance != DISTANCE:
            raise ConfigurationError(
                f"Qdrant collection '{self.collection_name}' stores {params.size}-dimensional "
                f"{params.distance} vectors, but the embedding model produces {dimension}-"
                f"dimensional {DISTANCE} vectors. Use a different QDRANT_COLLECTION_NAME or "
                "re-index with the original EMBEDDING_MODEL."
            )
        self._validated_dimension = dimension

    def _ensure_collection(self, client: QdrantClient, dimension: int) -> None:
        if not self._collection_exists(client):
            logger.info("Creating Qdrant collection %s (dim=%d)", self.collection_name, dimension)
            client.create_collection(
                self.collection_name,
                vectors_config=models.VectorParams(size=dimension, distance=DISTANCE),
            )
            if not self.is_local:  # payload indexes have no effect in local mode
                client.create_payload_index(
                    self.collection_name, "document_id", models.PayloadSchemaType.KEYWORD
                )
        self._check_dimension(client, dimension)

    @staticmethod
    def _validate_vectors(vectors: list[list[float]], dimension: int) -> None:
        for vector in vectors:
            if len(vector) != dimension:
                raise ConfigurationError(
                    f"Embedding has {len(vector)} dimensions; expected {dimension}."
                )

    # --- public API ------------------------------------------------------------
    def check_health(self) -> dict[str, Any]:
        def op(client: QdrantClient) -> dict[str, Any]:
            exists = self._collection_exists(client)
            points = client.count(self.collection_name, exact=True).count if exists else 0
            return {"collection_exists": exists, "points": points}

        return self._run("health check", op)

    def upsert_chunks(
        self,
        document: DocumentRecord,
        chunks: list[Chunk],
        vectors: list[list[float]],
        dimension: int,
    ) -> int:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        self._validate_vectors(vectors, dimension)
        points = [
            models.PointStruct(
                id=point_id_for(document.document_id, chunk.chunk_index),
                vector=vector,
                payload={
                    "document_id": document.document_id,
                    "filename": document.filename,
                    "file_type": document.file_type,
                    "total_pages": document.total_pages,
                    "ingested_at": document.ingested_at,
                    "embedding_model": document.embedding_model,
                    "page_number": chunk.page_number,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "token_count": chunk.token_count,
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]

        def op(client: QdrantClient) -> int:
            self._ensure_collection(client, dimension)
            client.upsert(self.collection_name, points=points, wait=True)
            return len(points)

        return self._run("upsert", op)

    def search(
        self,
        query_vector: list[float],
        top_k: int,
        dimension: int,
        document_ids: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        self._validate_vectors([query_vector], dimension)

        def op(client: QdrantClient) -> list[RetrievedChunk]:
            if not self._collection_exists(client):
                return []
            self._check_dimension(client, dimension)
            response = client.query_points(
                self.collection_name,
                query=query_vector,
                limit=top_k,
                query_filter=_document_filter(document_ids) if document_ids else None,
                with_payload=True,
            )
            return [self._to_retrieved(p) for p in response.points]

        return self._run("search", op)

    @staticmethod
    def _to_retrieved(point: models.ScoredPoint) -> RetrievedChunk:
        payload = point.payload or {}
        return RetrievedChunk(
            point_id=str(point.id),
            score=float(point.score),
            document_id=str(payload.get("document_id", "")),
            filename=str(payload.get("filename", "")),
            page_number=payload.get("page_number"),
            chunk_index=int(payload.get("chunk_index", 0)),
            text=str(payload.get("text", "")),
            char_start=payload.get("char_start"),
            char_end=payload.get("char_end"),
        )

    def list_documents(self) -> list[DocumentSummary]:
        fields = ["document_id", "filename", "file_type", "total_pages", "ingested_at"]

        def op(client: QdrantClient) -> list[DocumentSummary]:
            if not self._collection_exists(client):
                return []
            found: dict[str, dict[str, Any]] = {}
            offset: Any = None
            while True:
                records, offset = client.scroll(
                    self.collection_name,
                    limit=_SCROLL_PAGE,
                    offset=offset,
                    with_payload=fields,
                )
                for record in records:
                    payload = record.payload or {}
                    doc_id = str(payload.get("document_id", ""))
                    entry = found.setdefault(doc_id, {**payload, "chunk_count": 0})
                    entry["chunk_count"] += 1
                if offset is None:
                    break
            summaries = [
                DocumentSummary(
                    document_id=doc_id,
                    filename=str(p.get("filename", "")),
                    file_type=str(p.get("file_type", "")),
                    total_pages=p.get("total_pages"),
                    chunk_count=int(p["chunk_count"]),
                    ingested_at=str(p.get("ingested_at", "")),
                )
                for doc_id, p in found.items()
            ]
            return sorted(summaries, key=lambda s: s.ingested_at, reverse=True)

        return self._run("document listing", op)

    def delete_document(self, document_id: str) -> int:
        """Delete all chunks of a document; return the number of chunks removed."""

        def op(client: QdrantClient) -> int:
            if not self._collection_exists(client):
                return 0
            doc_filter = _document_filter([document_id])
            count = client.count(self.collection_name, count_filter=doc_filter, exact=True).count
            if count:
                client.delete(
                    self.collection_name,
                    points_selector=models.FilterSelector(filter=doc_filter),
                    wait=True,
                )
            return count

        return self._run("delete", op)

    def close(self) -> None:
        with self._guard():
            if self._client is not None:
                self._client.close()
                self._client = None
