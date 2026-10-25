/** Typed functions for each backend endpoint. Components call these, never `fetch`. */

import type {
  DeleteDocumentResponse,
  DocumentInfo,
  EvaluationDetail,
  EvaluationList,
  HealthResponse,
  IngestResponse,
  QueryRequest,
  QueryResponse,
  RunComparison,
  RunDetail,
  RunList,
  SystemStatus,
} from "../../types/api";
import { API_BASE_URL, request } from "./client";
import {
  isDeleteResponse,
  isDocumentList,
  isEvaluationDetail,
  isEvaluationList,
  isHealthResponse,
  isIngestResponse,
  isQueryResponse,
  isRunComparison,
  isRunDetail,
  isRunList,
  isSystemStatus,
} from "./guards";

// Generation on a local model can take a while; the backend's own Ollama timeout is 180 s.
const QUERY_TIMEOUT_MS = 200_000;
// The first ingest also loads the embedding model.
const INGEST_TIMEOUT_MS = 300_000;
const READ_TIMEOUT_MS = 15_000;
const HEALTH_TIMEOUT_MS = 8_000;
// Status runs live checks (model service, vector store, dataset validation, tracking store).
const STATUS_TIMEOUT_MS = 20_000;
// Reading the MLflow store loads MLflow on the first request.
const TRACKING_TIMEOUT_MS = 30_000;

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

// --- Read-only dashboards ----------------------------------------------------------------

const path = (...parts: string[]) => parts.map(encodeURIComponent).join("/");

export function listEvaluations(signal?: AbortSignal): Promise<EvaluationList> {
  return request("/evaluations", { timeoutMs: READ_TIMEOUT_MS, signal }, isEvaluationList);
}

export function getEvaluation(runId: string, signal?: AbortSignal): Promise<EvaluationDetail> {
  return request(`/evaluations/${path(runId)}`, { timeoutMs: READ_TIMEOUT_MS, signal }, isEvaluationDetail);
}

/** Download link for a saved report file (served as an attachment, paths redacted). */
export function evaluationFileUrl(runId: string, name: "report.json" | "report.md"): string {
  return `${API_BASE_URL}/evaluations/${path(runId, "files", name)}`;
}

export function listRuns(signal?: AbortSignal): Promise<RunList> {
  return request("/experiments/runs", { timeoutMs: TRACKING_TIMEOUT_MS, signal }, isRunList);
}

export function getRun(runId: string, signal?: AbortSignal): Promise<RunDetail> {
  return request(`/experiments/runs/${path(runId)}`, { timeoutMs: TRACKING_TIMEOUT_MS, signal }, isRunDetail);
}

export function compareRuns(baseline: string, candidate: string, signal?: AbortSignal): Promise<RunComparison> {
  const query = new URLSearchParams({ baseline, candidate }).toString();
  return request(`/experiments/compare?${query}`, { timeoutMs: TRACKING_TIMEOUT_MS, signal }, isRunComparison);
}

export function runArtifactUrl(runId: string, name: string): string {
  return `${API_BASE_URL}/experiments/runs/${path(runId, "artifacts", name)}`;
}

export function getSystemStatus(signal?: AbortSignal): Promise<SystemStatus> {
  return request("/system/status", { timeoutMs: STATUS_TIMEOUT_MS, signal }, isSystemStatus);
}
