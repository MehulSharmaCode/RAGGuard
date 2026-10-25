/**
 * The single HTTP client for the RAGGuard API. Every request goes through
 * `request`, which applies the base URL, timeouts, error normalisation, and
 * runtime validation of the response body.
 */

import type { ApiErrorBody, ApiErrorDetail } from "../../types/api";

// An empty VITE_API_BASE_URL is honoured on purpose: requests then go to the page's own origin,
// which is how the Docker Compose deployment reaches the API (Nginx proxies it; Stage 6, D-075).
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  "",
);

export type ApiErrorKind = "network" | "timeout" | "http" | "malformed" | "aborted" | "interrupted";

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly status: number | null;
  readonly code: string | null;
  readonly details: ApiErrorDetail[];

  constructor(
    kind: ApiErrorKind,
    message: string,
    options: { status?: number; code?: string; details?: ApiErrorDetail[] } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.status = options.status ?? null;
    this.code = options.code ?? null;
    this.details = options.details ?? [];
  }
}

export type Validator<T> = (value: unknown) => value is T;

export interface RequestOptions {
  method?: "GET" | "POST" | "DELETE";
  json?: unknown;
  body?: FormData;
  timeoutMs: number;
  signal?: AbortSignal;
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = (value as { error: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as { code?: unknown }).code === "string" &&
    typeof (error as { message?: unknown }).message === "string"
  );
}

async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

export async function request<T>(
  path: string,
  options: RequestOptions,
  validate: Validator<T>,
): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, options.timeoutMs);
  const onExternalAbort = () => controller.abort();
  options.signal?.addEventListener("abort", onExternalAbort);

  const init: RequestInit = { method: options.method ?? "GET", signal: controller.signal };
  if (options.json !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(options.json);
  } else if (options.body) {
    init.body = options.body;
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, init);
  } catch {
    if (timedOut) {
      throw new ApiError(
        "timeout",
        `The request timed out after ${Math.round(options.timeoutMs / 1000)} s.`,
      );
    }
    if (options.signal?.aborted) throw new ApiError("aborted", "The request was cancelled.");
    throw new ApiError(
      "network",
      `Cannot reach the RAGGuard API ${API_BASE_URL ? `at ${API_BASE_URL}` : "through this web server"}. Check that the backend is running.`,
    );
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", onExternalAbort);
  }

  const payload = await readJson(response);
  if (!response.ok) {
    if (isErrorBody(payload)) {
      throw new ApiError("http", payload.error.message, {
        status: response.status,
        code: payload.error.code,
        details: payload.error.details ?? [],
      });
    }
    throw new ApiError("http", `The server returned HTTP ${response.status}.`, {
      status: response.status,
    });
  }
  if (!validate(payload)) {
    throw new ApiError("malformed", "The server response did not match the expected format.", {
      status: response.status,
    });
  }
  return payload;
}
