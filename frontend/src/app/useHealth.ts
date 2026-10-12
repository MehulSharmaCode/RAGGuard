import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../lib/api/client";
import { getHealth } from "../lib/api/endpoints";
import type { HealthResponse } from "../types/api";

export interface HealthState {
  data: HealthResponse | null;
  /** Error of the most recent check; null if it succeeded. */
  error: ApiError | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

/** Real backend health from GET /health, re-checked periodically. Never assumed. */
export function useHealth(intervalMs = 30_000): HealthState {
  const [data, setData] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const requestId = useRef(0);

  // State changes only in the promise callbacks (never synchronously), and only for the latest request.
  const load = useCallback(() => {
    const id = ++requestId.current;
    const settle = (apply: () => void) => {
      if (id !== requestId.current) return;
      apply();
      setLoading(false);
    };
    return getHealth().then(
      (result) => settle(() => {
        setData(result);
        setError(null);
      }),
      (err: unknown) =>
        settle(() => setError(err instanceof ApiError ? err : new ApiError("malformed", "Health check failed."))),
    );
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    await load();
  }, [load]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void refresh(), intervalMs);
    return () => window.clearInterval(timer);
  }, [load, refresh, intervalMs]);

  return { data, error, loading, refresh };
}

export function maxUploadMb(health: HealthState): number | null {
  const value = health.data?.config.max_upload_size_mb;
  return typeof value === "number" ? value : null;
}
