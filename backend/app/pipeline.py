"""The RAG pipeline: ingestion and question answering.

This is the single implementation shared by the live API and (from Stage 4) the
offline evaluation runner. Components are injected so tests can use fakes.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from app.core.config import Settings
from app.core.errors import ConfigurationError, DocumentNotFoundError, EmptyDocumentError
from app.embeddings.base import Embedder
from app.generation.answer_check import check_answer
from app.generation.base import GenerationProvider
from app.generation.prompts import (
    FALLBACK_ANSWER,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_repair_prompt,
    build_user_prompt,
    cited_source_ids,
    is_declined,
    leaks_system_prompt,
    model_text,
    select_current_evidence,
    source_id,
)
from app.ingestion.chunking import chunk_pages
from app.ingestion.extraction import extract_document
from app.ingestion.validation import sanitize_filename, validate_upload
from app.retrieval.evidence import (
    EvidenceAssessment,
    FallbackReason,
    assess_evidence,
    evidence_threshold,
    merge_split_regions,
)
from app.retrieval.vector_store import DocumentRecord, QdrantVectorStore, RetrievedChunk
from app.schemas.documents import DeleteDocumentResponse, DocumentInfo, IngestResponse
from app.schemas.health import ComponentHealth, HealthResponse
from app.schemas.query import (
    EvidenceSummary,
    GenerationInfo,
    LatencyBreakdown,
    QueryRequest,
    QueryResponse,
    SourceReference,
)

logger = logging.getLogger(__name__)


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


@dataclass(frozen=True)
class EvidenceRetrieval:
    """Result of the retrieval stage of one query, before any generation.

    `retrieved` holds every top-k chunk with its cosine score, including chunks below
    the evidence threshold; `assessment.supporting` holds the ones used as evidence.
    `superseded` holds passing chunks of explicitly replaced documents that were withheld
    from the evidence because the question is not about history (D-070).
    """

    top_k: int
    retrieved: list[RetrievedChunk]
    assessment: EvidenceAssessment
    min_score_threshold: float
    embedding_ms: float
    retrieval_ms: float
    started_at: float  # time.perf_counter() when the query started
    superseded: tuple[RetrievedChunk, ...] = ()


class RAGPipeline:
    def __init__(
        self,
        settings: Settings,
        embedder: Embedder,
        vector_store: QdrantVectorStore,
        provider: GenerationProvider,
    ) -> None:
        self.settings = settings
        self.embedder = embedder
        self.vector_store = vector_store
        self.provider = provider

    # --- ingestion -------------------------------------------------------------
    def ingest(self, filename: str | None, content: bytes) -> IngestResponse:
        name = sanitize_filename(filename)
        file_type = validate_upload(name, content, self.settings.max_upload_bytes)
        extracted = extract_document(file_type, content)

        chunk_size = self.settings.chunk_size_tokens
        if chunk_size > self.embedder.max_input_tokens:
            raise ConfigurationError(
                f"CHUNK_SIZE_TOKENS={chunk_size} exceeds the embedding model input limit "
                f"of {self.embedder.max_input_tokens} tokens."
            )
        chunks = chunk_pages(
            extracted.pages, self.embedder, chunk_size, self.settings.chunk_overlap_tokens
        )
        if not chunks:
            raise EmptyDocumentError("The document contains no indexable text.")

        # One batch: each chunk's own text, then its structural sub-units (D-063).
        texts = [t for c in chunks for t in (c.text, *c.units)]
        flat = self.embedder.embed_documents(texts)
        vectors: list[list[list[float]]] = []
        position = 0
        for chunk in chunks:
            count = 1 + len(chunk.units)
            vectors.append(flat[position : position + count])
            position += count
        record = DocumentRecord(
            document_id=str(uuid.uuid4()),
            filename=name,
            file_type=file_type,
            total_pages=extracted.total_pages,
            ingested_at=datetime.now(UTC).isoformat(timespec="seconds"),
            embedding_model=self.embedder.model_name,
        )
        stored = self.vector_store.upsert_chunks(record, chunks, vectors, self.embedder.dimension)
        logger.info("Indexed document %s (%s): %d chunks", record.document_id, file_type, stored)
        return IngestResponse(
            document_id=record.document_id,
            filename=name,
            file_type=file_type,
            total_pages=extracted.total_pages,
            pages_with_text=len(extracted.pages),
            chunk_count=stored,
            status="indexed",
            ingested_at=record.ingested_at,
        )

    def list_documents(self) -> list[DocumentInfo]:
        return [
            DocumentInfo(
                document_id=d.document_id,
                filename=d.filename,
                file_type=d.file_type,
                total_pages=d.total_pages,
                chunk_count=d.chunk_count,
                status="indexed",
                ingested_at=d.ingested_at,
            )
            for d in self.vector_store.list_documents()
        ]

    def delete_document(self, document_id: str) -> DeleteDocumentResponse:
        deleted = self.vector_store.delete_document(document_id)
        if deleted == 0:
            raise DocumentNotFoundError("No indexed document has this ID.")
        return DeleteDocumentResponse(
            document_id=document_id, deleted_chunks=deleted, status="deleted"
        )

    # --- querying --------------------------------------------------------------
    def answer(self, request: QueryRequest) -> QueryResponse:
        return self.generate_answer(request, self.retrieve_evidence(request))

    def retrieve_evidence(self, request: QueryRequest) -> EvidenceRetrieval:
        """Embed the question, search Qdrant, and apply the evidence rule (no LLM call).

        Public so the offline evaluation can record every retrieved chunk and score,
        including those below the threshold that the API response does not expose.
        """
        started_at = time.perf_counter()
        top_k = request.top_k or self.settings.default_top_k
        document_ids = [str(d) for d in request.document_ids] if request.document_ids else None

        start = time.perf_counter()
        query_vector = self.embedder.embed_query(request.question)
        embedding_ms = _elapsed_ms(start)

        index_format = self.vector_store.index_format()
        threshold = evidence_threshold(self.settings.min_retrieval_score, index_format)
        start = time.perf_counter()
        retrieved = self.vector_store.search(
            query_vector,
            top_k,
            self.embedder.dimension,
            document_ids,
            query_text=request.question,
            min_score=threshold,
        )
        retrieval_ms = _elapsed_ms(start)

        assessment = assess_evidence(retrieved, threshold)
        if assessment.supporting:
            supporting = assessment.supporting
            # D-072: passages regain the rest of a region split across windows. Only
            # structure-aware indexes overlap chunks solely inside a split region; legacy
            # windows overlap everywhere, so they keep their old evidence.
            if index_format != "legacy":
                supporting = merge_split_regions(
                    supporting, self.vector_store.neighbours(supporting)
                )
            # D-070: explicitly replaced documents are withheld for current questions.
            supporting, superseded = select_current_evidence(request.question, supporting)
            assessment = replace(assessment, supporting=supporting)
        else:
            superseded = []
        return EvidenceRetrieval(
            top_k=top_k,
            retrieved=retrieved,
            assessment=assessment,
            min_score_threshold=threshold,
            embedding_ms=embedding_ms,
            retrieval_ms=retrieval_ms,
            started_at=started_at,
            superseded=tuple(superseded),
        )

    def generate_answer(self, request: QueryRequest, retrieval: EvidenceRetrieval) -> QueryResponse:
        """Return the fallback or call the LLM on the evidence from `retrieve_evidence`."""
        assessment = retrieval.assessment
        evidence = EvidenceSummary(
            retrieved_count=len(retrieval.retrieved),
            # Passages that passed the gate, including superseded ones withheld (D-070);
            # `sources` lists the passages actually supplied to the model.
            supporting_count=len(assessment.supporting) + len(retrieval.superseded),
            max_score=assessment.max_score,
            min_score_threshold=retrieval.min_score_threshold,
            top_k=retrieval.top_k,
        )

        def latency(generation_ms: float | None) -> LatencyBreakdown:
            return LatencyBreakdown(
                embedding_ms=retrieval.embedding_ms,
                retrieval_ms=retrieval.retrieval_ms,
                generation_ms=generation_ms,
                total_ms=_elapsed_ms(retrieval.started_at),
            )

        if assessment.fallback_reason is not None:
            logger.info("Fallback before generation: %s", assessment.fallback_reason)
            return self._fallback(assessment.fallback_reason, evidence, None, latency(None))

        supporting = assessment.supporting
        question = request.question
        texts = [model_text(question, chunk) for chunk in supporting]
        start = time.perf_counter()
        answer = self.provider.generate(SYSTEM_PROMPT, build_user_prompt(question, supporting))
        generation = GenerationInfo(
            provider=self.provider.name, model=self.provider.model, prompt_version=PROMPT_VERSION
        )

        # Output guards. The response contract (and the frontend's validator) only allows
        # three fallback reasons, so a withheld answer is reported as "model_declined" and
        # logged distinctly.
        problems: list[str] = []
        for attempt in range(2):
            if is_declined(answer):
                logger.info("Model declined: evidence judged insufficient")
                return self._fallback(
                    "model_declined", evidence, generation, latency(_elapsed_ms(start))
                )
            if leaks_system_prompt(answer):
                logger.warning("Answer withheld by output guard: it reproduced the system prompt")
                return self._fallback(
                    "model_declined", evidence, generation, latency(_elapsed_ms(start))
                )
            problems = check_answer(answer, supporting, texts, question)
            if not problems or attempt == 1:
                break
            # One bounded repair (D-071): regenerate with the reasons, never more.
            logger.warning("Answer rejected by the answer check (%s); regenerating once", problems)
            answer = self.provider.generate(
                SYSTEM_PROMPT, build_repair_prompt(question, supporting, problems)
            )
        generation_ms = _elapsed_ms(start)
        if problems:
            logger.warning("Answer withheld by the answer check: %s", "; ".join(problems))
            return self._fallback("model_declined", evidence, generation, latency(generation_ms))

        cited = set(cited_source_ids(answer, {source_id(i) for i in range(len(supporting))}))
        return QueryResponse(
            answer=answer,
            status="answered",
            answerable=True,
            fallback_reason=None,
            sources=[
                _to_reference(position, chunk, cited) for position, chunk in enumerate(supporting)
            ],
            evidence=evidence,
            generation=generation,
            latency_ms=latency(generation_ms),
        )

    @staticmethod
    def _fallback(
        reason: FallbackReason,
        evidence: EvidenceSummary,
        generation: GenerationInfo | None,
        latency: LatencyBreakdown,
    ) -> QueryResponse:
        return QueryResponse(
            answer=FALLBACK_ANSWER,
            status="insufficient_evidence",
            answerable=False,
            fallback_reason=reason,
            sources=[],
            evidence=evidence,
            generation=generation,
            latency_ms=latency,
        )

    # --- health ----------------------------------------------------------------
    def health(self) -> HealthResponse:
        components: dict[str, ComponentHealth] = {}

        try:
            store = self.vector_store.check_health()
            components["vector_store"] = ComponentHealth(
                status="ok",
                detail=f"{'local' if self.vector_store.is_local else 'remote'} Qdrant; "
                f"collection exists: {store['collection_exists']}; points: {store['points']}; "
                + {
                    "hybrid": "index: hybrid (sub-unit + lexical vectors)",
                    "subunit": "index: sub-unit vectors (re-upload documents for hybrid retrieval, "
                    "D-064)",
                    "legacy": "index: legacy single-vector (re-upload documents to migrate, D-063)",
                }.get(str(store["index_format"]), f"index: {store['index_format']}"),
            )
        except Exception as exc:  # health must report, not raise
            message = getattr(exc, "message", "Vector store check failed.")
            components["vector_store"] = ComponentHealth(status="unavailable", detail=message)

        components["embedding"] = ComponentHealth(
            status="loaded" if self.embedder.is_loaded else "not_loaded",
            detail="Loaded in memory."
            if self.embedder.is_loaded
            else "Loads on first ingest or query.",
        )

        provider_status = self.provider.check_readiness()
        components["generation"] = ComponentHealth(
            status=provider_status.state, detail=provider_status.detail
        )

        healthy = components["vector_store"].status == "ok" and provider_status.ready
        return HealthResponse(
            status="ok" if healthy else "degraded",
            api="ok",
            generation_ready=provider_status.ready,
            components=components,
            config={
                "generation_provider": self.provider.name,
                "generation_model": self.provider.model,
                "embedding_model": self.embedder.model_name,
                "qdrant_mode": "local" if self.vector_store.is_local else "remote",
                "qdrant_collection": self.vector_store.collection_name,
                "chunk_size_tokens": self.settings.chunk_size_tokens,
                "chunk_overlap_tokens": self.settings.chunk_overlap_tokens,
                "default_top_k": self.settings.default_top_k,
                "min_retrieval_score": self.settings.min_retrieval_score,
                "max_upload_size_mb": self.settings.max_upload_size_mb,
                "prompt_version": PROMPT_VERSION,
            },
        )


def _to_reference(position: int, chunk: RetrievedChunk, cited: set[str]) -> SourceReference:
    sid = source_id(position)
    return SourceReference(
        source_id=sid,
        document_id=chunk.document_id,
        filename=chunk.filename,
        page_number=chunk.page_number,
        chunk_index=chunk.chunk_index,
        char_start=chunk.char_start,
        char_end=chunk.char_end,
        excerpt=chunk.text,
        score=round(chunk.score, 4),
        cited=sid in cited,
    )
