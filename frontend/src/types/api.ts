/**
 * Types mirroring the backend Pydantic schemas exactly
 * (backend/app/schemas/*.py). The backend is the source of truth.
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

// --- Read-only dashboards (backend/app/schemas/{evaluations,experiments,system}.py) ---

export type MetricKind = "rate" | "mean" | "count" | "ms";
export type MetricDirection = "higher" | "lower" | "neutral";

export interface MetricValue {
  key: string;
  label: string;
  group: string;
  direction: MetricDirection;
  kind: MetricKind;
  supplementary: boolean;
  /** False when the report or run does not record this metric (never shown as zero). */
  available: boolean;
  /** Null when unavailable or when no case applied (denominator 0). */
  value: number | null;
  numerator: number | null;
  denominator: number | null;
}

export interface EvaluationSummary {
  run_id: string;
  readable: boolean;
  problem: string | null;
  schema_version: string | null;
  detail_supported: boolean;
  started_at: string | null;
  finished_at: string | null;
  status: string | null;
  status_detail: string | null;
  rescored_from: string | null;
  dataset_id: string | null;
  dataset_version: string | null;
  dataset_fingerprint: string | null;
  cases_run: number | null;
  cases_in_dataset: number | null;
  params: Record<string, string>;
  headline: MetricValue[];
}

export interface EvaluationList {
  results_dir: string;
  reports: EvaluationSummary[];
}

export interface LatencySummary {
  count: number;
  mean_ms: number | null;
  median_ms: number | null;
  p95_ms: number | null;
  min_ms: number | null;
  max_ms: number | null;
}

export interface JudgeSummary {
  enabled: boolean;
  model: string | null;
  same_model_as_generation: boolean | null;
  eligible_cases: number | null;
  scored: number | null;
  not_applicable: number | null;
  errors: string[];
}

export type FindingKind =
  | "pipeline_error"
  | "false_refusal"
  | "false_answer"
  | "missing_facts"
  | "unsupported_content"
  | "attack_succeeded"
  | "canary_leak"
  | "invalid_citation"
  | "superseded_citation"
  | "unsupported_citation"
  | "uncited_fact"
  | "retrieval_miss"
  | "judge_error"
  | "judge_flag";

export interface Finding {
  kind: FindingKind;
  detail: string;
}

export interface PassageView {
  rank: number;
  filename: string;
  page_number: number | null;
  score: number;
  above_threshold: boolean;
  source_id: string | null;
  cited: boolean;
  excerpt: string;
}

export interface AttackView {
  scenario_id: string;
  vector: string;
  channel: string;
  status: string;
  reasons: string[];
  canary_leaked: boolean | null;
  echoed: string[];
  task_completed: boolean | null;
}

export interface JudgeView {
  status: string;
  correctness: number | null;
  groundedness: number | null;
  completeness: number | null;
  unsupported_claims: boolean | null;
  citations_support_claims: boolean | null;
  unanswerable_handled_correctly: boolean | null;
  rationale: string | null;
  error: string | null;
}

export type CaseVerdict = "pass" | "fail" | "error" | "unscored";

export interface CaseView {
  case_id: string;
  category: string;
  answerability: string;
  question: string;
  reference_answer: string | null;
  expected_sources: string[];
  superseded_sources: string[];
  required_facts: string[];
  notes: string | null;
  verdict: CaseVerdict;
  outcome: string | null;
  fallback_reason: string | null;
  answer: string | null;
  llm_called: boolean | null;
  max_score: number | null;
  latency_ms: number | null;
  facts_found: string[];
  facts_missing: string[];
  cited_filenames: string[];
  invalid_citation_ids: string[];
  findings: Finding[];
  attack: AttackView | null;
  diagnostic: string | null;
  judge: JudgeView | null;
  error: string | null;
  retrieved: PassageView[];
}

export interface MetricDefinition {
  name: string;
  definition: string;
  denominator: string;
}

export interface EvaluationDetail {
  summary: EvaluationSummary;
  fatal_error: string | null;
  metrics: MetricValue[];
  latency: Record<string, LatencySummary>;
  judge: JudgeSummary | null;
  cases: CaseView[];
  metric_definitions: MetricDefinition[];
  limitations: string[];
}

export type TrackingState = "available" | "empty" | "no_store" | "dependency_missing" | "unavailable";

export interface TrackingStatus {
  state: TrackingState;
  detail: string;
  store: string;
  experiment_name: string;
  run_count: number | null;
}

export interface RunSummary {
  run_id: string;
  run_name: string | null;
  status: string;
  start_time: string | null;
  end_time: string | null;
  label: string | null;
  ragguard_run_id: string | null;
  imported: boolean;
  rescored_from: string | null;
  git_commit: string | null;
  git_dirty: string | null;
  local_report: boolean;
  params: Record<string, string>;
  metrics: MetricValue[];
}

export interface RunList {
  tracking: TrackingStatus;
  runs: RunSummary[];
}

export interface RunDetail {
  run: RunSummary;
  artifacts: string[];
  all_metrics: Record<string, number>;
}

export type Assessment = "improved" | "regressed" | "unchanged" | "changed" | "not_comparable" | "unavailable";

export interface ParamDiff {
  key: string;
  label: string;
  baseline: string | null;
  candidate: string | null;
  changed: boolean;
}

export interface MetricDelta {
  key: string;
  label: string;
  group: string;
  supplementary: boolean;
  baseline: MetricValue;
  candidate: MetricValue;
  delta: number | null;
  assessment: Assessment;
}

export interface RunComparison {
  baseline: RunSummary;
  candidate: RunSummary;
  comparable: boolean;
  notes: string[];
  params: ParamDiff[];
  metrics: MetricDelta[];
  improved: string[];
  regressed: string[];
}

export type ComponentState = "healthy" | "configured" | "unavailable" | "not_implemented";

export interface ComponentStatus {
  id: string;
  label: string;
  state: ComponentState;
  detail: string;
  verified: boolean;
}

export interface SystemStatus {
  checked_at: string;
  components: ComponentStatus[];
  configuration: Record<string, string | number | null>;
  latest_evaluation: EvaluationSummary | null;
  evaluation_report_count: number;
  tracking: TrackingStatus;
}
