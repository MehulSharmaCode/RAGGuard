/** Runtime checks that API responses have the shape the UI relies on. */

import type {
  CaseView,
  ComponentStatus,
  DeleteDocumentResponse,
  DocumentInfo,
  DocumentListResponse,
  EvaluationDetail,
  EvaluationList,
  EvaluationSummary,
  HealthResponse,
  IngestResponse,
  MetricDelta,
  MetricValue,
  QueryResponse,
  RunComparison,
  RunDetail,
  RunList,
  RunSummary,
  SourceReference,
  SystemStatus,
  TrackingStatus,
} from "../../types/api";

type Obj = Record<string, unknown>;

const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isNumOrNull = (v: unknown): v is number | null => v === null || isNum(v);
const isStrOrNull = (v: unknown): v is string | null => v === null || isStr(v);
const isBool = (v: unknown): v is boolean => typeof v === "boolean";
const isStrArray = (v: unknown): v is string[] => Array.isArray(v) && v.every(isStr);
const isStrRecord = (v: unknown): v is Record<string, string> => isObj(v) && Object.values(v).every(isStr);

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

// --- Read-only dashboards -------------------------------------------------------------

export function isMetricValue(v: unknown): v is MetricValue {
  return (
    isObj(v) &&
    isStr(v.key) &&
    isStr(v.label) &&
    isStr(v.group) &&
    (v.direction === "higher" || v.direction === "lower" || v.direction === "neutral") &&
    (v.kind === "rate" || v.kind === "mean" || v.kind === "count" || v.kind === "ms") &&
    isBool(v.supplementary) &&
    isBool(v.available) &&
    isNumOrNull(v.value) &&
    isNumOrNull(v.numerator) &&
    isNumOrNull(v.denominator)
  );
}

function isEvaluationSummary(v: unknown): v is EvaluationSummary {
  return (
    isObj(v) &&
    isStr(v.run_id) &&
    isBool(v.readable) &&
    isStrOrNull(v.problem) &&
    isStrOrNull(v.schema_version) &&
    isBool(v.detail_supported) &&
    isStrOrNull(v.started_at) &&
    isStrOrNull(v.status) &&
    isStrOrNull(v.dataset_version) &&
    isStrOrNull(v.dataset_fingerprint) &&
    isNumOrNull(v.cases_run) &&
    isStrRecord(v.params) &&
    Array.isArray(v.headline) &&
    v.headline.every(isMetricValue)
  );
}

export function isEvaluationList(v: unknown): v is EvaluationList {
  return isObj(v) && isStr(v.results_dir) && Array.isArray(v.reports) && v.reports.every(isEvaluationSummary);
}

function isCaseView(v: unknown): v is CaseView {
  return (
    isObj(v) &&
    isStr(v.case_id) &&
    isStr(v.category) &&
    isStr(v.question) &&
    (v.verdict === "pass" || v.verdict === "fail" || v.verdict === "error" || v.verdict === "unscored") &&
    isStrOrNull(v.answer) &&
    isStrOrNull(v.reference_answer) &&
    isStrArray(v.expected_sources) &&
    isStrArray(v.facts_missing) &&
    Array.isArray(v.findings) &&
    v.findings.every((f) => isObj(f) && isStr(f.kind) && isStr(f.detail)) &&
    Array.isArray(v.retrieved) &&
    v.retrieved.every((p) => isObj(p) && isStr(p.filename) && isNum(p.score) && isStr(p.excerpt)) &&
    (v.attack === null || (isObj(v.attack) && isStr(v.attack.status) && isStrArray(v.attack.reasons))) &&
    (v.judge === null || (isObj(v.judge) && isStr(v.judge.status)))
  );
}

export function isEvaluationDetail(v: unknown): v is EvaluationDetail {
  return (
    isObj(v) &&
    isEvaluationSummary(v.summary) &&
    Array.isArray(v.metrics) &&
    v.metrics.every(isMetricValue) &&
    isObj(v.latency) &&
    Array.isArray(v.cases) &&
    v.cases.every(isCaseView) &&
    Array.isArray(v.metric_definitions) &&
    isStrArray(v.limitations)
  );
}

function isTrackingStatus(v: unknown): v is TrackingStatus {
  return (
    isObj(v) &&
    ["available", "empty", "no_store", "dependency_missing", "unavailable"].includes(v.state as string) &&
    isStr(v.detail) &&
    isStr(v.store) &&
    isStr(v.experiment_name) &&
    isNumOrNull(v.run_count)
  );
}

function isRunSummary(v: unknown): v is RunSummary {
  return (
    isObj(v) &&
    isStr(v.run_id) &&
    isStrOrNull(v.run_name) &&
    isStr(v.status) &&
    isStrOrNull(v.start_time) &&
    isStrOrNull(v.label) &&
    isStrOrNull(v.ragguard_run_id) &&
    isBool(v.imported) &&
    isBool(v.local_report) &&
    isStrRecord(v.params) &&
    Array.isArray(v.metrics) &&
    v.metrics.every(isMetricValue)
  );
}

export function isRunList(v: unknown): v is RunList {
  return isObj(v) && isTrackingStatus(v.tracking) && Array.isArray(v.runs) && v.runs.every(isRunSummary);
}

export function isRunDetail(v: unknown): v is RunDetail {
  return (
    isObj(v) &&
    isRunSummary(v.run) &&
    isStrArray(v.artifacts) &&
    isObj(v.all_metrics) &&
    Object.values(v.all_metrics).every(isNum)
  );
}

function isMetricDelta(v: unknown): v is MetricDelta {
  return (
    isObj(v) &&
    isStr(v.key) &&
    isStr(v.label) &&
    isMetricValue(v.baseline) &&
    isMetricValue(v.candidate) &&
    isNumOrNull(v.delta) &&
    ["improved", "regressed", "unchanged", "changed", "not_comparable", "unavailable"].includes(
      v.assessment as string,
    )
  );
}

export function isRunComparison(v: unknown): v is RunComparison {
  return (
    isObj(v) &&
    isRunSummary(v.baseline) &&
    isRunSummary(v.candidate) &&
    isBool(v.comparable) &&
    isStrArray(v.notes) &&
    Array.isArray(v.params) &&
    v.params.every((p) => isObj(p) && isStr(p.key) && isStr(p.label) && isBool(p.changed)) &&
    Array.isArray(v.metrics) &&
    v.metrics.every(isMetricDelta) &&
    isStrArray(v.improved) &&
    isStrArray(v.regressed)
  );
}

function isComponentStatus(v: unknown): v is ComponentStatus {
  return (
    isObj(v) &&
    isStr(v.id) &&
    isStr(v.label) &&
    ["healthy", "configured", "unavailable", "not_implemented"].includes(v.state as string) &&
    isStr(v.detail) &&
    isBool(v.verified)
  );
}

export function isSystemStatus(v: unknown): v is SystemStatus {
  return (
    isObj(v) &&
    isStr(v.checked_at) &&
    Array.isArray(v.components) &&
    v.components.every(isComponentStatus) &&
    isObj(v.configuration) &&
    (v.latest_evaluation === null || isEvaluationSummary(v.latest_evaluation)) &&
    isNum(v.evaluation_report_count) &&
    isTrackingStatus(v.tracking)
  );
}
