import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api/client";

export interface Resource<T> {
  data: T | null;
  /** Error of the latest request for the current key; null when it succeeded or is running. */
  error: ApiError | null;
  loading: boolean;
  refresh: () => void;
}

interface Settled<T> {
  key: string;
  nonce: number;
  data: T | null;
  error: ApiError | null;
}

/**
 * Loads `key`'s data with `load` and reloads when the key changes or on refresh().
 * A null key loads nothing. Older responses are ignored and in-flight requests are
 * aborted. State changes only in promise callbacks (no synchronous setState in effects).
 */
export function useResource<T>(key: string | null, load: (signal: AbortSignal) => Promise<T>): Resource<T> {
  const [nonce, setNonce] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const loadRef = useRef(load);

  useEffect(() => {
    loadRef.current = load;
  });

  useEffect(() => {
    if (key === null) return;
    const controller = new AbortController();
    loadRef.current(controller.signal).then(
      (data) => setSettled({ key, nonce, data, error: null }),
      (err: unknown) => {
        const error = err instanceof ApiError ? err : new ApiError("malformed", "Unexpected error while loading.");
        if (error.kind === "aborted") return;
        // Keep the previous data of the same key visible next to the error.
        setSettled((prev) => ({ key, nonce, data: prev?.key === key ? prev.data : null, error }));
      },
    );
    return () => controller.abort();
  }, [key, nonce]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);
  const current = settled !== null && settled.key === key ? settled : null;
  return {
    data: current?.data ?? null,
    error: current !== null && current.nonce === nonce ? current.error : null,
    loading: key !== null && (current === null || current.nonce !== nonce),
    refresh,
  };
}
