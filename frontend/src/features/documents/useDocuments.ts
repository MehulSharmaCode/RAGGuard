import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../../lib/api/client";
import { deleteDocument, ingestDocument, listDocuments } from "../../lib/api/endpoints";
import type { DocumentInfo, IngestResponse } from "../../types/api";

function toApiError(error: unknown): ApiError {
  return error instanceof ApiError
    ? error
    : new ApiError("malformed", "Unexpected error while talking to the API.");
}

export interface DocumentsState {
  documents: DocumentInfo[] | null;
  loading: boolean;
  error: ApiError | null;
  refresh: () => Promise<void>;
  remove: (documentId: string) => Promise<void>;
}

/** The server-side document list. Never cached or filled with placeholder data. */
export function useDocuments(): DocumentsState {
  const [documents, setDocuments] = useState<DocumentInfo[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const requestId = useRef(0);

  // State changes only in the promise callbacks (never synchronously), and only for the latest request.
  const load = useCallback(() => {
    const id = ++requestId.current;
    const settle = (apply: () => void) => {
      if (id !== requestId.current) return;
      apply();
      setLoading(false);
    };
    return listDocuments().then(
      (result) => settle(() => {
        setDocuments(result);
        setError(null);
      }),
      (err: unknown) => settle(() => setError(toApiError(err))),
    );
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    await load();
  }, [load]);

  useEffect(() => {
    void load();
  }, [load]);

  const remove = useCallback(
    async (documentId: string) => {
      try {
        await deleteDocument(documentId);
      } catch (err) {
        throw toApiError(err);
      }
      await refresh();
    },
    [refresh],
  );

  return { documents, loading, error, refresh, remove };
}

export type UploadState =
  | { phase: "idle" }
  | { phase: "uploading"; filename: string; size: number; startedAt: number }
  | { phase: "indexed"; result: IngestResponse }
  | { phase: "rejected"; filename: string; title: string; message: string; code: string | null };

const SUPPORTED = /\.(pdf|txt)$/i;

/** Checks the browser can make before sending; the backend remains authoritative. */
export function precheckFile(file: File, maxBytes: number | null): string | null {
  if (!SUPPORTED.test(file.name)) return "Only PDF (.pdf) and plain-text (.txt) files are supported.";
  if (file.size === 0) return "The file is empty.";
  if (maxBytes !== null && file.size > maxBytes) {
    return `The file is ${(file.size / (1024 * 1024)).toFixed(1)} MB; the limit is ${(maxBytes / (1024 * 1024)).toFixed(0)} MB.`;
  }
  return null;
}

export function useUpload(maxBytes: number | null, onIndexed: (result: IngestResponse) => void) {
  const [state, setState] = useState<UploadState>({ phase: "idle" });
  const inFlight = useRef(false);

  const upload = useCallback(
    async (file: File) => {
      if (inFlight.current) return; // one upload at a time; duplicate submissions are ignored
      const problem = precheckFile(file, maxBytes);
      if (problem) {
        setState({
          phase: "rejected",
          filename: file.name,
          title: `${file.name} was not uploaded`,
          message: problem,
          code: null,
        });
        return;
      }
      inFlight.current = true;
      setState({ phase: "uploading", filename: file.name, size: file.size, startedAt: Date.now() });
      try {
        const result = await ingestDocument(file);
        setState({ phase: "indexed", result });
        onIndexed(result);
      } catch (err) {
        const error = toApiError(err);
        setState({
          phase: "rejected",
          filename: file.name,
          title: `${file.name} was not indexed`,
          message: error.message,
          code: error.code,
        });
      } finally {
        inFlight.current = false;
      }
    },
    [maxBytes, onIndexed],
  );

  const reset = useCallback(() => setState({ phase: "idle" }), []);
  return { state, upload, reset };
}
