/**
 * Test fixtures shaped exactly like real backend responses (copied in structure from
 * the Stage 2 smoke test). Used only by tests; never imported by application code.
 */

import type { DocumentInfo, HealthResponse, QueryResponse } from "../types/api";

export const HANDBOOK_ID = "5a81e6aa-d692-44ea-bc6f-45799a905a0f";
export const NOTES_ID = "8f75f021-c426-4b1c-b91e-d48b6cf9c003";

export const healthOk: HealthResponse = {
  status: "ok",
  api: "ok",
  generation_ready: true,
  components: {
    vector_store: { status: "ok", detail: "local Qdrant; collection exists: True; points: 4" },
    embedding: { status: "loaded", detail: "Loaded in memory." },
    generation: { status: "ready", detail: "Model 'qwen3.5:9b' is installed." },
  },
  config: {
    generation_provider: "ollama",
    generation_model: "qwen3.5:9b",
    embedding_model: "sentence-transformers/all-MiniLM-L6-v2",
    qdrant_mode: "local",
    qdrant_collection: "ragguard_chunks",
    chunk_size_tokens: 180,
    chunk_overlap_tokens: 30,
    default_top_k: 4,
    min_retrieval_score: 0.35,
    max_upload_size_mb: 1,
    prompt_version: "v1",
  },
};

export const healthDegraded: HealthResponse = {
  ...healthOk,
  status: "degraded",
  generation_ready: false,
  components: {
    ...healthOk.components,
    generation: { status: "unavailable", detail: "The Ollama service is not reachable." },
  },
};

export const handbook: DocumentInfo = {
  document_id: HANDBOOK_ID,
  filename: "handbook.pdf",
  file_type: "pdf",
  total_pages: 3,
  chunk_count: 3,
  status: "indexed",
  ingested_at: "2026-10-12T18:10:05+00:00",
};

export const notes: DocumentInfo = {
  document_id: NOTES_ID,
  filename: "notes.txt",
  file_type: "txt",
  total_pages: null,
  chunk_count: 1,
  status: "indexed",
  ingested_at: "2026-10-12T18:10:06+00:00",
};

export const answered: QueryResponse = {
  answer:
    "Employees receive 25 days of paid annual leave per calendar year [S1]. Unused leave of up to 5 days may be carried over [S1]. Interpretation: leave beyond 5 days is lost at year end.",
  status: "answered",
  answerable: true,
  fallback_reason: null,
  sources: [
    {
      source_id: "S1",
      document_id: HANDBOOK_ID,
      filename: "handbook.pdf",
      page_number: 2,
      chunk_index: 1,
      char_start: 0,
      char_end: 142,
      excerpt:
        "Section 2: Leave. Employees receive 25 days of paid annual leave per calendar year. Unused leave of up to 5 days may be carried over to the next year.",
      score: 0.8771,
      cited: true,
    },
    {
      source_id: "S2",
      document_id: NOTES_ID,
      filename: "notes.txt",
      page_number: null,
      chunk_index: 0,
      char_start: 0,
      char_end: 120,
      excerpt: "Project Kestrel notes. Project Kestrel is led by Dana Okafor.",
      score: 0.4012,
      cited: false,
    },
  ],
  evidence: { retrieved_count: 4, supporting_count: 2, max_score: 0.8771, min_score_threshold: 0.35, top_k: 4 },
  generation: { provider: "ollama", model: "qwen3.5:9b", prompt_version: "v1" },
  latency_ms: { embedding_ms: 43.2, retrieval_ms: 0.8, generation_ms: 811.2, total_ms: 855.3 },
};

export const belowThreshold: QueryResponse = {
  answer:
    "The uploaded documents did not provide sufficient evidence to answer this question reliably, so no answer was generated. Try rephrasing the question, selecting different documents, or uploading a document that covers this topic.",
  status: "insufficient_evidence",
  answerable: false,
  fallback_reason: "below_threshold",
  sources: [],
  evidence: { retrieved_count: 4, supporting_count: 0, max_score: 0.3131, min_score_threshold: 0.35, top_k: 4 },
  generation: null,
  latency_ms: { embedding_ms: 5.6, retrieval_ms: 0.4, generation_ms: null, total_ms: 6.1 },
};

export const modelDeclined: QueryResponse = {
  ...belowThreshold,
  fallback_reason: "model_declined",
  evidence: { retrieved_count: 1, supporting_count: 1, max_score: 0.666, min_score_threshold: 0.35, top_k: 4 },
  generation: { provider: "ollama", model: "qwen3.5:9b", prompt_version: "v1" },
  latency_ms: { embedding_ms: 6, retrieval_ms: 0.5, generation_ms: 640, total_ms: 650 },
};
