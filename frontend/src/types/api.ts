/**
 * Types mirroring the backend Pydantic schemas exactly
 * (backend/app/schemas/{documents,query,health}.py). The backend is the source of truth.
 */

export type FileType = "pdf" | "txt";

export interface IngestResponse {
  document_id: string;
  filename: string;
  file_type: FileType;
  total_pages: number | null;
  pages_with_text: number;
  chunk_count: number;
  status: "indexed";
  ingested_at: string;
}

export interface DocumentInfo {
  document_id: string;
  filename: string;
  file_type: string;
  total_pages: number | null;
  chunk_count: number;
  status: "indexed";
  ingested_at: string;
}

export interface DocumentListResponse {
  documents: DocumentInfo[];
}

export interface DeleteDocumentResponse {
  document_id: string;
  deleted_chunks: number;
  status: "deleted";
}

export interface QueryRequest {
  question: string;
  document_ids?: string[];
  top_k?: number;
}

export interface SourceReference {
  source_id: string;
  document_id: string;
  filename: string;
  page_number: number | null;
  chunk_index: number;
  char_start: number | null;
  char_end: number | null;
  excerpt: string;
  score: number;
  cited: boolean;
}

export interface EvidenceSummary {
  retrieved_count: number;
  supporting_count: number;
  max_score: number | null;
  min_score_threshold: number;
  top_k: number;
}

export interface GenerationInfo {
  provider: string;
  model: string;
  prompt_version: string;
}

export interface LatencyBreakdown {
  embedding_ms: number;
  retrieval_ms: number;
  generation_ms: number | null;
  total_ms: number;
}

export type QueryStatus = "answered" | "insufficient_evidence";
export type FallbackReason = "no_results" | "below_threshold" | "model_declined";

export interface QueryResponse {
  answer: string;
  status: QueryStatus;
  answerable: boolean;
  fallback_reason: FallbackReason | null;
  sources: SourceReference[];
  evidence: EvidenceSummary;
  generation: GenerationInfo | null;
  latency_ms: LatencyBreakdown;
}

export interface ComponentHealth {
  status: string;
  detail: string;
}

export interface HealthResponse {
  status: "ok" | "degraded";
  api: "ok";
  generation_ready: boolean;
  components: Record<string, ComponentHealth>;
  config: Record<string, string | number | null>;
}

export interface ApiErrorDetail {
  location: (string | number)[];
  message: string;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: ApiErrorDetail[] };
}
