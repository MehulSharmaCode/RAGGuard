"""Qdrant storage and similarity search for document chunks.

One point per chunk. Vectors are L2-normalized and the collection uses COSINE
distance, so Qdrant scores are cosine similarities in [-1, 1] (higher is closer).

Index formats, newest first:
- "hybrid" (D-064, 2026-10-16): named vectors — "dense", the whole chunk plus its
  structural sub-units compared with MAX_SIM (a chunk's score is its best vector's
  cosine), and "lexical", a BM25-weighted sparse vector with Qdrant's IDF modifier.
  Search fuses the dense and lexical rankings (reciprocal rank fusion) to choose up to
  `top_k` chunks whose dense score reaches `min_score`, and returns them in dense-score
  order (then the closest remaining chunks); the returned score is always the dense
  score, so the evidence threshold keeps its meaning.
- "subunit" (D-063): the dense multivector only, searched by dense score.
- "legacy" (before D-063): one vector per point, searched with a plain vector.
Older formats keep working unchanged and new uploads into them use their format; an
empty older collection is recreated as "hybrid" on the next upload; one that holds
documents is never dropped (re-upload the documents to migrate them, D-025).

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
from typing import Any, Literal, TypeVar

from qdrant_client import QdrantClient, models

from app.core.config import Settings
from app.core.errors import ConfigurationError, VectorStoreError
from app.ingestion.chunking import Chunk
from app.retrieval.lexical import document_vector, reciprocal_rank_fusion
from app.retrieval.lexical import query_vector as lexical_query

logger = logging.getLogger(__name__)

DISTANCE = models.Distance.COSINE
_POINT_NAMESPACE = uuid.UUID("6f2b8f0e-6c55-4d1e-9a51-6b8c2c7f1a10")
_SCROLL_PAGE = 256

T = TypeVar("T")

IndexFormat = Literal["hybrid", "subunit", "legacy"]
# Recorded in evaluation reports and MLflow to identify the retrieval representation.
RETRIEVAL_INDEX = (
    "hybrid: sub-unit dense vectors (MAX_SIM) + BM25 sparse vectors, rank fusion, "
    "dense-score gate (D-063, D-064)"
)
DENSE, LEXICAL = "dense", "lexical"
# Candidates taken from each ranking before fusion (at least this many, or 5 x top_k).
_FUSION_CANDIDATES = 20


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
        self._format: IndexFormat | None = None
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

    def _params(self, client: QdrantClient) -> models.VectorParams:
        """The dense vector parameters (the unnamed vector, or the "dense" named one)."""
        params = client.get_collection(self.collection_name).config.params.vectors
        if isinstance(params, dict) and isinstance(params.get(DENSE), models.VectorParams):
            return params[DENSE]
        if not isinstance(params, models.VectorParams):
            raise ConfigurationError(
                "The Qdrant collection uses named vectors that RAGGuard did not create."
            )
        return params

    def _index_format(self, client: QdrantClient) -> IndexFormat:
        if self._format is None:
            vectors = client.get_collection(self.collection_name).config.params.vectors
            if isinstance(vectors, dict):
                self._params(client)  # validates the named layout
                self._format = "hybrid"
            else:
                params = self._params(client)
                self._format = "subunit" if params.multivector_config is not None else "legacy"
        return self._format

    def _check_dimension(self, client: QdrantClient, dimension: int) -> None:
        if self._validated_dimension == dimension:
            return
        params = self._params(client)
        if params.size != dimension or params.distance != DISTANCE:
            raise ConfigurationError(
                f"Qdrant collection '{self.collection_name}' stores {params.size}-dimensional "
                f"{params.distance} vectors, but the embedding model produces {dimension}-"
                f"dimensional {DISTANCE} vectors. Use a different QDRANT_COLLECTION_NAME or "
                "re-index with the original EMBEDDING_MODEL."
            )
        self._validated_dimension = dimension

    def _ensure_collection(self, client: QdrantClient, dimension: int) -> None:
        exists = self._collection_exists(client)
        if (
            exists
            and self._index_format(client) != "hybrid"
            and client.count(self.collection_name, exact=True).count == 0
        ):
            logger.info(
                "Recreating empty %s collection %s as hybrid index",
                self._index_format(client),
                self.collection_name,
            )
            client.delete_collection(self.collection_name)
            self._format = None
            exists = False
        if not exists:
            logger.info("Creating Qdrant collection %s (dim=%d)", self.collection_name, dimension)
            client.create_collection(
                self.collection_name,
                vectors_config={
                    DENSE: models.VectorParams(
                        size=dimension,
                        distance=DISTANCE,
                        multivector_config=models.MultiVectorConfig(
                            comparator=models.MultiVectorComparator.MAX_SIM
                        ),
                    )
                },
                sparse_vectors_config={
                    LEXICAL: models.SparseVectorParams(modifier=models.Modifier.IDF)
                },
            )
            self._format = "hybrid"
            self._validated_dimension = None
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
    def index_format(self) -> IndexFormat:
        """Format of the collection; a collection that does not exist yet will be "hybrid"."""

        def op(client: QdrantClient) -> IndexFormat:
            return self._index_format(client) if self._collection_exists(client) else "hybrid"

        return self._run("index format check", op)

    def check_health(self) -> dict[str, Any]:
        def op(client: QdrantClient) -> dict[str, Any]:
            exists = self._collection_exists(client)
            points = client.count(self.collection_name, exact=True).count if exists else 0
            index = self._index_format(client) if exists else "hybrid"
            return {"collection_exists": exists, "points": points, "index_format": index}

        return self._run("health check", op)

    def upsert_chunks(
        self,
        document: DocumentRecord,
        chunks: list[Chunk],
        vectors: list[list[list[float]]],
        dimension: int,
    ) -> int:
        """Store one point per chunk; `vectors[i]` is the whole-chunk vector followed by
        the vectors of the chunk's sub-units (only the first is kept in a legacy index; the
        hybrid index also stores a lexical vector of the chunk text)."""
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        if any(not v for v in vectors):
            raise ValueError("every chunk needs at least its whole-chunk vector")
        self._validate_vectors([v for chunk_vectors in vectors for v in chunk_vectors], dimension)

        def vector(fmt: IndexFormat, chunk: Chunk, chunk_vectors: list[list[float]]) -> Any:
            if fmt == "legacy":
                return chunk_vectors[0]
            if fmt == "subunit":
                return chunk_vectors
            indices, values = document_vector(chunk.text)
            return {
                DENSE: chunk_vectors,
                LEXICAL: models.SparseVector(indices=indices, values=values),
            }

        def build(fmt: IndexFormat) -> list[models.PointStruct]:
            subunit = fmt != "legacy"
            return [
                models.PointStruct(
                    id=point_id_for(document.document_id, chunk.chunk_index),
                    vector=vector(fmt, chunk, chunk_vectors),
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
                        "subunits": list(chunk.units) if subunit else [],
                    },
                )
                for chunk, chunk_vectors in zip(chunks, vectors, strict=True)
            ]

        def op(client: QdrantClient) -> int:
            self._ensure_collection(client, dimension)
            fmt = self._index_format(client)
            if fmt != "hybrid":
                logger.warning(
                    "Collection %s uses the older %s index; new chunks are stored in that format. "
                    "Delete and re-upload its documents to migrate to the hybrid index.",
                    self.collection_name,
                    fmt,
                )
            points = build(fmt)
            client.upsert(self.collection_name, points=points, wait=True)
            return len(points)

        return self._run("upsert", op)

    def search(
        self,
        query_vector: list[float],
        top_k: int,
        dimension: int,
        document_ids: list[str] | None = None,
        *,
        query_text: str | None = None,
        min_score: float | None = None,
    ) -> list[RetrievedChunk]:
        """Up to `top_k` chunks with their dense scores.

        Older formats: the `top_k` highest dense scores. Hybrid index with `query_text`:
        the first `top_k` chunks of the fused ranking whose dense score reaches
        `min_score`, ordered by dense score, then (to report what was closest) the best
        remaining chunks by dense score.
        """
        self._validate_vectors([query_vector], dimension)

        def op(client: QdrantClient) -> list[RetrievedChunk]:
            if not self._collection_exists(client):
                return []
            self._check_dimension(client, dimension)
            query_filter = _document_filter(document_ids) if document_ids else None
            fmt = self._index_format(client)
            if fmt != "hybrid" or not query_text:
                query: list[float] | list[list[float]] = (
                    query_vector if fmt == "legacy" else [query_vector]
                )
                response = client.query_points(
                    self.collection_name,
                    query=query,
                    using=DENSE if fmt == "hybrid" else None,
                    limit=top_k,
                    query_filter=query_filter,
                    with_payload=True,
                )
                return [self._to_retrieved(p) for p in response.points]
            return self._hybrid_search(
                client, query_vector, query_text, top_k, query_filter, min_score
            )

        return self._run("search", op)

    def _hybrid_search(
        self,
        client: QdrantClient,
        query_vector: list[float],
        query_text: str,
        top_k: int,
        query_filter: models.Filter | None,
        min_score: float | None,
    ) -> list[RetrievedChunk]:
        limit = max(_FUSION_CANDIDATES, 5 * top_k)
        dense = client.query_points(
            self.collection_name,
            query=[query_vector],
            using=DENSE,
            limit=limit,
            query_filter=query_filter,
            with_payload=True,
        ).points
        found = {str(p.id): self._to_retrieved(p) for p in dense}
        lexical_ids: list[str] = []
        indices, values = lexical_query(query_text)
        if indices:
            lexical = client.query_points(
                self.collection_name,
                query=models.SparseVector(indices=indices, values=values),
                using=LEXICAL,
                limit=limit,
                query_filter=query_filter,
                with_payload=False,
            ).points
            lexical_ids = [str(p.id) for p in lexical]
            missing = [pid for pid in lexical_ids if pid not in found]
            if missing:  # lexical-only candidates still need their dense score
                rescored = client.query_points(
                    self.collection_name,
                    query=[query_vector],
                    using=DENSE,
                    limit=len(missing),
                    query_filter=models.Filter(
                        must=[models.HasIdCondition(has_id=list[int | str | uuid.UUID](missing))]
                    ),
                    with_payload=True,
                ).points
                found.update({str(p.id): self._to_retrieved(p) for p in rescored})
        fused = reciprocal_rank_fusion([str(p.id) for p in dense], lexical_ids)
        ranked = [found[pid] for pid in fused if pid in found]
        floor = min_score if min_score is not None else float("-inf")
        passing = [c for c in ranked if c.score >= floor][:top_k]
        # Fusion decides WHICH chunks become evidence; they are presented in dense-score
        # order, so a lexically promoted chunk never outranks stronger semantic evidence
        # in the prompt (measured 2026-10-16: fused order let distractors and injected
        # passages move to S2 and changed model behaviour; D-064 amendment).
        passing.sort(key=lambda c: -c.score)
        rest = sorted((c for c in ranked if c.score < floor), key=lambda c: -c.score)
        return passing + rest[: top_k - len(passing)]

    def neighbours(self, chunks: list[RetrievedChunk]) -> dict[tuple[str, int], RetrievedChunk]:
        """The chunks directly before and after each given chunk, keyed by
        (document_id, chunk_index), with score 0 (read-only; used by D-072)."""
        wanted: dict[str, set[int]] = {}
        for chunk in chunks:
            wanted.setdefault(chunk.document_id, set()).update(
                {chunk.chunk_index - 1, chunk.chunk_index + 1}
            )

        def op(client: QdrantClient) -> dict[tuple[str, int], RetrievedChunk]:
            found: dict[tuple[str, int], RetrievedChunk] = {}
            if not self._collection_exists(client):
                return found
            for document_id, indexes in wanted.items():
                records, _ = client.scroll(
                    self.collection_name,
                    scroll_filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="document_id", match=models.MatchValue(value=document_id)
                            ),
                            models.FieldCondition(
                                key="chunk_index", match=models.MatchAny(any=sorted(indexes))
                            ),
                        ]
                    ),
                    limit=len(indexes),
                    with_payload=True,
                    with_vectors=False,
                )
                for record in records:
                    neighbour = self._to_retrieved(record)
                    found[(neighbour.document_id, neighbour.chunk_index)] = neighbour
            return found

        return self._run("neighbour lookup", op)

    @staticmethod
    def _to_retrieved(point: models.ScoredPoint | models.Record) -> RetrievedChunk:
        payload = point.payload or {}
        return RetrievedChunk(
            point_id=str(point.id),
            score=float(getattr(point, "score", 0.0) or 0.0),
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
