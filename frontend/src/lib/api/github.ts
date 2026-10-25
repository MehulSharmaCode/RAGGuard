/**
 * Recent GitHub Actions runs for the Pipeline view (Stage 7, D-083, U-015).
 *
 * The browser reads GitHub's public REST API anonymously: no token exists anywhere in the
 * bundle, so only public data can be read and the anonymous limit (60 requests per hour per
 * network) applies. The response is validated at runtime, kept in sessionStorage for a few
 * minutes (the page never polls), and shown as "stale" when GitHub cannot be reached and an
 * older copy is used. A run's link is accepted only if it points at this repository's run page.
 * Nothing here is part of the RAGGuard API.
 */

import { ApiError } from "./client";

const DEFAULT_REPOSITORY = "MehulSharmaCode/RAGGuard";
const REPOSITORY_PATTERN = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;

/** `owner/name`, or null when VITE_GITHUB_REPOSITORY is set to something that is not one. */
export function configuredRepository(): string | null {
  const value = (import.meta.env.VITE_GITHUB_REPOSITORY ?? DEFAULT_REPOSITORY).trim();
  return REPOSITORY_PATTERN.test(value) ? value : null;
}

export const RUNS_PER_PAGE = 10;
/** Cached runs younger than this are shown without asking GitHub again. */
export const CACHE_TTL_MS = 5 * 60 * 1000;
const TIMEOUT_MS = 10_000;
const CACHE_KEY = "ragguard.ci-runs.v1";

export type RunState =
  | "success"
  | "failure"
  | "cancelled"
  | "in_progress"
  | "queued"
  | "action_required"
  | "other";

export interface CiRun {
  id: number;
  workflowName: string;
  title: string;
  runNumber: number;
  attempt: number;
  event: string;
  branch: string | null;
  /** Full 40-character commit SHA. */
  commit: string;
  status: string;
  conclusion: string | null;
  state: RunState;
  /** https://github.com/<owner>/<repo>/actions/runs/<id> */
  url: string;
  createdAt: string;
  updatedAt: string;
}

export interface RateLimit {
  limit: number | null;
  remaining: number | null;
  /** ISO time at which the window resets, if GitHub said. */
  resetAt: string | null;
}

export interface CiRuns {
  repository: string;
  runs: CiRun[];
  /** When these runs were read from GitHub (ISO). */
  fetchedAt: string;
  /** True when no request was made because a recent copy was available. */
  fromCache: boolean;
  /** Why an older copy is shown instead of fresh data; null for current data. */
  staleReason: string | null;
  rateLimit: RateLimit | null;
}

export function actionsUrl(repository: string): string {
  return `https://github.com/${repository}/actions`;
}

export function commitUrl(repository: string, sha: string): string {
  return `https://github.com/${repository}/commit/${sha}`;
}

export function runState(status: string, conclusion: string | null): RunState {
  if (status === "completed") {
    switch (conclusion) {
      case "success":
        return "success";
      case "failure":
      case "timed_out":
      case "startup_failure":
        return "failure";
      case "cancelled":
        return "cancelled";
      case "action_required":
        return "action_required";
      default:
        return "other"; // skipped, neutral, stale, or a value this client does not know
    }
  }
  if (status === "in_progress") return "in_progress";
  if (status === "queued" || status === "waiting" || status === "requested" || status === "pending") return "queued";
  return "other";
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isCount = (value: unknown): value is number => typeof value === "number" && Number.isInteger(value) && value >= 0;
const isText = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const isDate = (value: unknown): value is string => typeof value === "string" && !Number.isNaN(Date.parse(value));
const isNullableText = (value: unknown): value is string | null => value === null || typeof value === "string";

function runUrlPattern(repository: string, id: number): string {
  return `https://github.com/${repository}/actions/runs/${id}`;
}

/** One run from the API response, or null if any field is missing, mistyped, or its link is foreign. */
function toRun(raw: unknown, repository: string): CiRun | null {
  if (!isRecord(raw)) return null;
  const { id, name, display_title, run_number, run_attempt, event, head_branch, head_sha } = raw;
  const { status, conclusion, html_url, created_at, updated_at } = raw;
  if (!isCount(id) || !isCount(run_number) || !isCount(run_attempt)) return null;
  if (!isNullableText(name) || !isNullableText(display_title) || !isText(event)) return null;
  if (!isNullableText(head_branch) || typeof head_sha !== "string" || !/^[0-9a-f]{40}$/.test(head_sha)) return null;
  if (!isText(status) || !isNullableText(conclusion)) return null;
  if (html_url !== runUrlPattern(repository, id)) return null;
  if (!isDate(created_at) || !isDate(updated_at)) return null;
  return {
    id,
    workflowName: name ?? "workflow",
    title: display_title ?? name ?? "workflow run",
    runNumber: run_number,
    attempt: run_attempt,
    event,
    branch: head_branch,
    commit: head_sha,
    status,
    conclusion,
    state: runState(status, conclusion),
    url: html_url,
    createdAt: created_at,
    updatedAt: updated_at,
  };
}

/** Validates a GitHub `workflow_runs` response. Returns null unless every run is well formed. */
export function parseRuns(payload: unknown, repository: string): CiRun[] | null {
  if (!isRecord(payload) || !Array.isArray(payload.workflow_runs)) return null;
  const runs: CiRun[] = [];
  for (const raw of payload.workflow_runs) {
    const run = toRun(raw, repository);
    if (run === null) return null;
    runs.push(run);
  }
  return runs;
}

function isCiRun(value: unknown, repository: string): value is CiRun {
  if (!isRecord(value)) return false;
  const run = toRun(
    {
      id: value.id,
      name: value.workflowName,
      display_title: value.title,
      run_number: value.runNumber,
      run_attempt: value.attempt,
      event: value.event,
      head_branch: value.branch,
      head_sha: value.commit,
      status: value.status,
      conclusion: value.conclusion,
      html_url: value.url,
      created_at: value.createdAt,
      updated_at: value.updatedAt,
    },
    repository,
  );
  return run !== null && run.state === value.state;
}

interface Stored {
  repository: string;
  fetchedAt: string;
  runs: CiRun[];
  rateLimit: RateLimit | null;
}

function readCache(repository: string): Stored | null {
  try {
    const parsed: unknown = JSON.parse(window.sessionStorage.getItem(CACHE_KEY) ?? "null");
    if (!isRecord(parsed) || parsed.repository !== repository || !isDate(parsed.fetchedAt)) return null;
    if (!Array.isArray(parsed.runs) || !parsed.runs.every((run) => isCiRun(run, repository))) return null;
    return {
      repository,
      fetchedAt: parsed.fetchedAt,
      runs: parsed.runs as CiRun[],
      rateLimit: isRateLimit(parsed.rateLimit) ? parsed.rateLimit : null,
    };
  } catch {
    return null; // storage unavailable or not JSON: behave as if nothing was cached
  }
}

function writeCache(stored: Stored): void {
  try {
    window.sessionStorage.setItem(CACHE_KEY, JSON.stringify(stored));
  } catch {
    // Private mode or a full quota: the runs are still shown, just not cached.
  }
}

function isRateLimit(value: unknown): value is RateLimit {
  return (
    isRecord(value) &&
    (value.limit === null || isCount(value.limit)) &&
    (value.remaining === null || isCount(value.remaining)) &&
    (value.resetAt === null || isDate(value.resetAt))
  );
}

function headerCount(response: Response, name: string): number | null {
  const raw = response.headers.get(name);
  if (raw === null || !/^\d+$/.test(raw)) return null;
  return Number(raw);
}

function rateLimitOf(response: Response): RateLimit | null {
  const limit = headerCount(response, "x-ratelimit-limit");
  const remaining = headerCount(response, "x-ratelimit-remaining");
  const reset = headerCount(response, "x-ratelimit-reset");
  if (limit === null && remaining === null && reset === null) return null;
  return { limit, remaining, resetAt: reset === null ? null : new Date(reset * 1000).toISOString() };
}

async function fetchRuns(repository: string, signal: AbortSignal): Promise<{ runs: CiRun[]; rateLimit: RateLimit | null }> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, TIMEOUT_MS);
  const onAbort = () => controller.abort();
  signal.addEventListener("abort", onAbort);
  let response: Response;
  try {
    response = await fetch(`https://api.github.com/repos/${repository}/actions/runs?per_page=${RUNS_PER_PAGE}`, {
      headers: { Accept: "application/vnd.github+json" },
      signal: controller.signal,
    });
  } catch {
    if (timedOut) throw new ApiError("timeout", "GitHub did not answer within 10 s.");
    if (signal.aborted) throw new ApiError("aborted", "The request was cancelled.");
    throw new ApiError("network", "Cannot reach api.github.com. Check the network connection.");
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", onAbort);
  }

  const rateLimit = rateLimitOf(response);
  if (response.status === 429 || (response.status === 403 && rateLimit?.remaining === 0)) {
    const reset = rateLimit?.resetAt ? ` It resets at ${new Date(rateLimit.resetAt).toLocaleTimeString()}.` : "";
    throw new ApiError(
      "http",
      `GitHub's anonymous API rate limit is used up (60 requests per hour per network).${reset}`,
      { status: response.status, code: "rate_limited" },
    );
  }
  if (response.status === 404) {
    throw new ApiError("http", `GitHub has no public Actions data for ${repository} (HTTP 404). The repository may be private or renamed.`, {
      status: 404,
      code: "not_found",
    });
  }
  if (!response.ok) {
    throw new ApiError("http", `GitHub returned HTTP ${response.status}.`, { status: response.status });
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    payload = undefined;
  }
  const runs = parseRuns(payload, repository);
  if (runs === null) {
    throw new ApiError("malformed", "GitHub's response did not match the expected format, so no runs are shown.", {
      status: response.status,
    });
  }
  return { runs, rateLimit };
}

/**
 * Recent runs of the repository's workflows. Reuses a copy younger than CACHE_TTL_MS unless
 * `force`; when GitHub cannot be reached and an older copy exists, returns it with a
 * `staleReason` instead of an error. Throws ApiError when there is nothing honest to show.
 */
export async function getCiRuns(signal: AbortSignal, options: { force?: boolean } = {}): Promise<CiRuns> {
  const repository = configuredRepository();
  if (repository === null) {
    throw new ApiError("malformed", "VITE_GITHUB_REPOSITORY is not an owner/name repository, so CI runs cannot be read.");
  }
  const cached = readCache(repository);
  if (cached && !options.force && Date.now() - Date.parse(cached.fetchedAt) < CACHE_TTL_MS) {
    return { ...cached, fromCache: true, staleReason: null };
  }
  try {
    const { runs, rateLimit } = await fetchRuns(repository, signal);
    const stored: Stored = { repository, fetchedAt: new Date().toISOString(), runs, rateLimit };
    writeCache(stored);
    return { ...stored, fromCache: false, staleReason: null };
  } catch (err) {
    if (err instanceof ApiError && err.kind !== "aborted" && cached) {
      return { ...cached, fromCache: true, staleReason: err.message };
    }
    throw err;
  }
}
