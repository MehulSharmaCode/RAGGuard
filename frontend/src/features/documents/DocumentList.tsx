import { FileText, RotateCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "../../components/ui/Button";
import { InlineAlert } from "../../components/ui/InlineAlert";
import { StatusTag } from "../../components/ui/StatusTag";
import type { ApiError } from "../../lib/api/client";
import { formatDateTime, plural, shortId } from "../../lib/format";
import type { DocumentInfo } from "../../types/api";

export interface DocumentListProps {
  documents: DocumentInfo[] | null;
  loading: boolean;
  error: ApiError | null;
  onRetry: () => void;
  onRemove: (documentId: string) => Promise<void>;
  scope: ReadonlySet<string>;
  onToggleScope: (documentId: string) => void;
}

function DocumentRow({
  doc,
  inScope,
  onToggleScope,
  onRemove,
}: {
  doc: DocumentInfo;
  inScope: boolean;
  onToggleScope: () => void;
  onRemove: () => Promise<void>;
}) {
  const [confirming, setConfirming] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const checkboxId = `scope-${doc.document_id}`;

  const confirmRemove = async () => {
    setRemoving(true);
    setError(null);
    try {
      await onRemove();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The document could not be removed.");
      setRemoving(false);
    }
  };

  const meta = [
    doc.file_type.toUpperCase(),
    doc.total_pages !== null ? plural(doc.total_pages, "page") : null,
    plural(doc.chunk_count, "chunk"),
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <li className="border-b border-paper-300 py-3 last:border-b-0">
      <div className="flex items-start gap-2.5">
        <input
          id={checkboxId}
          type="checkbox"
          checked={inScope}
          onChange={onToggleScope}
          className="mt-1 size-4 shrink-0 accent-[var(--ink-900)]"
          aria-label={`Limit questions to ${doc.filename}`}
        />
        <FileText aria-hidden="true" size={16} strokeWidth={1.5} className="mt-0.5 shrink-0 text-ink-500" />
        <div className="min-w-0 flex-1">
          <label htmlFor={checkboxId} className="block truncate text-14 text-ink-900" title={doc.filename}>
            {doc.filename}
          </label>
          <p className="tnum font-mono text-12 text-ink-500">{meta}</p>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <StatusTag tone="pass">Indexed</StatusTag>
            <span className="tnum text-12 text-ink-500">{formatDateTime(doc.ingested_at)}</span>
          </div>
          <p className="font-mono text-12 text-ink-500" title={doc.document_id}>
            id {shortId(doc.document_id)}
          </p>
        </div>
        {!confirming && (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            aria-label={`Remove ${doc.filename}`}
            title="Remove from index"
            className="rounded-sm p-1.5 text-ink-500 hover:bg-paper-200 hover:text-fail"
          >
            <Trash2 aria-hidden="true" size={16} strokeWidth={1.75} />
          </button>
        )}
      </div>
      {confirming && (
        <div className="mt-2 ml-7 rounded-sm border border-paper-300 bg-paper-50 p-2.5" role="group" aria-label={`Confirm removal of ${doc.filename}`}>
          <p className="text-13 text-ink-700">
            Remove <span className="font-medium text-ink-900">{doc.filename}</span> and its{" "}
            {plural(doc.chunk_count, "chunk")} from the index? Answers already on screen keep their
            excerpts.
          </p>
          {error && <p className="mt-1 text-13 text-fail" role="alert">{error}</p>}
          <div className="mt-2 flex gap-2">
            <Button size="sm" variant="destructive" icon={Trash2} loading={removing} onClick={confirmRemove}>
              Remove
            </Button>
            <Button size="sm" variant="ghost" disabled={removing} onClick={() => { setConfirming(false); setError(null); }}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

export function DocumentList({
  documents,
  loading,
  error,
  onRetry,
  onRemove,
  scope,
  onToggleScope,
}: DocumentListProps) {
  if (documents === null && loading) {
    return (
      <div aria-busy="true" className="space-y-3 py-2">
        <span className="sr-only">Loading documents</span>
        {[0, 1, 2].map((i) => (
          <div key={i} className="space-y-1.5" aria-hidden="true">
            <div className="h-3.5 w-3/4 rounded-xs bg-paper-200" />
            <div className="h-3 w-1/2 rounded-xs bg-paper-200" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {error && (
        <InlineAlert
          tone="error"
          title="Could not load the document list"
          action={
            <Button size="sm" icon={RotateCw} onClick={onRetry} loading={loading}>
              Retry
            </Button>
          }
        >
          {error.message}
          {documents !== null && " Showing the last list received from the server."}
        </InlineAlert>
      )}
      {documents !== null && documents.length === 0 && !error && (
        <p className="py-2 text-13 text-ink-500">No documents indexed yet.</p>
      )}
      {documents !== null && documents.length > 0 && (
        <ul aria-label="Indexed documents">
          {documents.map((doc) => (
            <DocumentRow
              key={doc.document_id}
              doc={doc}
              inScope={scope.has(doc.document_id)}
              onToggleScope={() => onToggleScope(doc.document_id)}
              onRemove={() => onRemove(doc.document_id)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
