/** Runtime checks that API responses have the shape the UI relies on. */

import type {
  DeleteDocumentResponse,
  DocumentInfo,
  DocumentListResponse,
  HealthResponse,
  IngestResponse,
  QueryResponse,
  SourceReference,
} from "../../types/api";

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isNumOrNull = (v: unknown): v is number | null => v === null || isNum(v);

function isDocumentFields(v: Obj): boolean {
  return (
    isStr(v.document_id) &&
    isStr(v.filename) &&
    isStr(v.file_type) &&
    isNumOrNull(v.total_pages) &&
    isNum(v.chunk_count) &&
    v.status === "indexed" &&
    isStr(v.ingested_at)
  );
}

export function isDocumentInfo(v: unknown): v is DocumentInfo {
  return isObj(v) && isDocumentFields(v);
}

export function isDocumentList(v: unknown): v is DocumentListResponse {
  return isObj(v) && Array.isArray(v.documents) && v.documents.every(isDocumentInfo);
}

export function isIngestResponse(v: unknown): v is IngestResponse {
  return (
    isObj(v) &&
    isDocumentFields(v) &&
    (v.file_type === "pdf" || v.file_type === "txt") &&
    isNum(v.pages_with_text)
  );
}

export function isDeleteResponse(v: unknown): v is DeleteDocumentResponse {
  return isObj(v) && isStr(v.document_id) && isNum(v.deleted_chunks) && v.status === "deleted";
}

function isSource(v: unknown): v is SourceReference {
  return (
    isObj(v) &&
    isStr(v.source_id) &&
    isStr(v.document_id) &&
    isStr(v.filename) &&
    isNumOrNull(v.page_number) &&
    isNum(v.chunk_index) &&
    isNumOrNull(v.char_start) &&
    isNumOrNull(v.char_end) &&
    isStr(v.excerpt) &&
    isNum(v.score) &&
    typeof v.cited === "boolean"
  );
}

export function isQueryResponse(v: unknown): v is QueryResponse {
  if (!isObj(v) || !isObj(v.evidence) || !isObj(v.latency_ms)) return false;
  const { evidence, latency_ms: latency, generation } = v;
  return (
    isStr(v.answer) &&
    (v.status === "answered" || v.status === "insufficient_evidence") &&
    typeof v.answerable === "boolean" &&
    (v.fallback_reason === null ||
      v.fallback_reason === "no_results" ||
      v.fallback_reason === "below_threshold" ||
      v.fallback_reason === "model_declined") &&
    Array.isArray(v.sources) &&
    v.sources.every(isSource) &&
    isNum(evidence.retrieved_count) &&
    isNum(evidence.supporting_count) &&
    isNumOrNull(evidence.max_score) &&
    isNum(evidence.min_score_threshold) &&
    isNum(evidence.top_k) &&
    (generation === null ||
      (isObj(generation) &&
        isStr(generation.provider) &&
        isStr(generation.model) &&
        isStr(generation.prompt_version))) &&
    isNum(latency.embedding_ms) &&
    isNum(latency.retrieval_ms) &&
    isNumOrNull(latency.generation_ms) &&
    isNum(latency.total_ms)
  );
}

export function isHealthResponse(v: unknown): v is HealthResponse {
  return (
    isObj(v) &&
    (v.status === "ok" || v.status === "degraded") &&
    v.api === "ok" &&
    typeof v.generation_ready === "boolean" &&
    isObj(v.components) &&
    Object.values(v.components).every((c) => isObj(c) && isStr(c.status) && isStr(c.detail)) &&
    isObj(v.config)
  );
}
