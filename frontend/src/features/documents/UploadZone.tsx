import { FileUp, Upload, X } from "lucide-react";
import { useEffect, useState, type DragEvent, type RefObject } from "react";
import { Button } from "../../components/ui/Button";
import { InlineAlert } from "../../components/ui/InlineAlert";
import { StatusTag } from "../../components/ui/StatusTag";
import { formatBytes, plural } from "../../lib/format";
import type { UploadState } from "./useDocuments";

function Elapsed({ since }: { since: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return <span className="tnum font-mono">{Math.max(0, Math.round((now - since) / 1000))} s</span>;
}

export interface UploadZoneProps {
  state: UploadState;
  onFile: (file: File) => void;
  onDismiss: () => void;
  maxUploadMb: number | null;
  disabledReason: string | null;
  inputRef: RefObject<HTMLInputElement | null>;
}

export function UploadZone({
  state,
  onFile,
  onDismiss,
  maxUploadMb,
  disabledReason,
  inputRef,
}: UploadZoneProps) {
  const [dragging, setDragging] = useState(false);
  const [multiNotice, setMultiNotice] = useState(false);
  const busy = state.phase === "uploading";
  const disabled = busy || disabledReason !== null;

  const takeFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setMultiNotice(files.length > 1);
    onFile(files[0]!);
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    if (!disabled) takeFiles(event.dataTransfer.files);
  };

  const limit = maxUploadMb !== null ? `up to ${maxUploadMb} MB` : "size limit unknown";

  return (
    <div className="space-y-3">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        data-dragging={dragging || undefined}
        className={`rounded-md border border-dashed px-4 py-4 transition-colors duration-150 ${
          dragging ? "border-accent-500 bg-paper-50" : "border-line-strong bg-paper-50/60"
        } ${disabled ? "opacity-70" : ""}`}
      >
        <div className="flex items-start gap-3">
          <FileUp aria-hidden="true" size={20} strokeWidth={1.5} className="mt-0.5 shrink-0 text-ink-500" />
          <div className="min-w-0">
            <p className="text-14 text-ink-900">Drop a PDF or TXT file here</p>
            <p className="tnum text-12 text-ink-500">One file at a time · {limit}</p>
          </div>
        </div>
        <Button
          className="mt-3 w-full"
          icon={Upload}
          onClick={() => inputRef.current?.click()}
          disabled={disabled}
          loading={busy}
        >
          {busy ? "Indexing…" : "Choose file"}
        </Button>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.txt,application/pdf,text/plain"
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
          aria-label="Upload a PDF or TXT document"
          disabled={disabled}
          onChange={(event) => {
            takeFiles(event.target.files);
            event.target.value = "";
          }}
        />
        {disabledReason && !busy && <p className="mt-2 text-12 text-ink-500">{disabledReason}</p>}
      </div>

      <div aria-live="polite" className="space-y-2">
        {multiNotice && state.phase !== "idle" && (
          <p className="text-12 text-ink-500">Only the first file was taken; upload others one at a time.</p>
        )}
        {state.phase === "uploading" && (
          <div className="rounded-sm border border-paper-300 bg-paper-50 px-3 py-2.5">
            <StatusTag tone="loading">
              Indexing <span className="font-medium text-ink-900">{state.filename}</span>
            </StatusTag>
            <p className="mt-1 text-12 text-ink-500">
              {formatBytes(state.size)} sent. The server extracts, chunks, and embeds the text, then
              reports the result; it does not report step-by-step progress. Elapsed{" "}
              <Elapsed since={state.startedAt} />.
            </p>
          </div>
        )}
        {state.phase === "indexed" && (
          <div className="flex items-start justify-between gap-2 rounded-sm border border-paper-300 bg-paper-50 px-3 py-2.5">
            <div className="min-w-0">
              <StatusTag tone="pass">
                Indexed · <span className="tnum font-mono">{plural(state.result.chunk_count, "chunk")}</span>
              </StatusTag>
              <p className="mt-1 truncate text-12 text-ink-500" title={state.result.filename}>
                {state.result.filename}
                {state.result.total_pages !== null &&
                  ` · ${plural(state.result.pages_with_text, "page")} with text of ${state.result.total_pages}`}
              </p>
            </div>
            <button
              type="button"
              onClick={onDismiss}
              aria-label="Dismiss upload result"
              className="rounded-xs p-1 text-ink-500 hover:bg-paper-200 hover:text-ink-900"
            >
              <X aria-hidden="true" size={16} strokeWidth={1.75} />
            </button>
          </div>
        )}
        {state.phase === "rejected" && (
          <InlineAlert
            tone="error"
            title={state.title}
            action={
              <Button size="sm" variant="ghost" onClick={onDismiss}>
                Dismiss
              </Button>
            }
          >
            {state.message}
            {state.code && <span className="ml-1 font-mono text-12 text-ink-500">({state.code})</span>}
          </InlineAlert>
        )}
      </div>
    </div>
  );
}
