/** Typed functions for each backend endpoint. Components call these, never `fetch`. */

import type {
  DeleteDocumentResponse,
  DocumentInfo,
  HealthResponse,
  IngestResponse,
  QueryRequest,
  QueryResponse,
} from "../../types/api";
import { request } from "./client";
import {
  isDeleteResponse,
  isDocumentList,
  isHealthResponse,
  isIngestResponse,
  isQueryResponse,
} from "./guards";

// Generation on a local model can take a while; the backend's own Ollama timeout is 180 s.
const QUERY_TIMEOUT_MS = 200_000;
// The first ingest also loads the embedding model.
const INGEST_TIMEOUT_MS = 300_000;
const READ_TIMEOUT_MS = 15_000;
const HEALTH_TIMEOUT_MS = 8_000;

export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return request("/health", { timeoutMs: HEALTH_TIMEOUT_MS, signal }, isHealthResponse);
}

export async function listDocuments(signal?: AbortSignal): Promise<DocumentInfo[]> {
  const body = await request("/documents", { timeoutMs: READ_TIMEOUT_MS, signal }, isDocumentList);
  return body.documents;
}

export function ingestDocument(file: File, signal?: AbortSignal): Promise<IngestResponse> {
  const form = new FormData();
  form.append("file", file, file.name);
  return request(
    "/ingest",
    { method: "POST", body: form, timeoutMs: INGEST_TIMEOUT_MS, signal },
    isIngestResponse,
  );
}

export function deleteDocument(documentId: string): Promise<DeleteDocumentResponse> {
  return request(
    `/documents/${encodeURIComponent(documentId)}`,
    { method: "DELETE", timeoutMs: READ_TIMEOUT_MS },
    isDeleteResponse,
  );
}

export function queryDocuments(body: QueryRequest, signal?: AbortSignal): Promise<QueryResponse> {
  return request(
    "/query",
    { method: "POST", json: body, timeoutMs: QUERY_TIMEOUT_MS, signal },
    isQueryResponse,
  );
}
