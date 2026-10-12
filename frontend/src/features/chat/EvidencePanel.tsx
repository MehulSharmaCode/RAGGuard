import { Quote, X } from "lucide-react";
import { useEffect, useRef } from "react";
import { formatScore, pageLabel, plural, shortId } from "../../lib/format";
import type { QueryResponse, SourceReference } from "../../types/api";
import type { Turn } from "./useConversation";

function EvidenceItem({
  source,
  selected,
  onSelect,
}: {
  source: SourceReference;
  selected: boolean;
  onSelect: () => void;
}) {
  const ref = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView?.({ block: "nearest" });
  }, [selected]);

  return (
    <li
      ref={ref}
      className={`border-b border-l-2 border-b-paper-300 py-3 pr-1 pl-3 ${
        selected ? "border-l-accent-500 bg-paper-50" : "border-l-transparent"
      }`}
    >
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className="flex w-full items-start gap-2 rounded-xs text-left"
      >
        <span
          className={`mt-0.5 rounded-xs border px-1 font-mono text-12 ${
            selected ? "border-accent-500 bg-accent-300 text-on-accent" : "border-paper-300 bg-paper-200 text-ink-700"
          }`}
        >
          {source.source_id}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-14 text-ink-900" title={source.filename}>{source.filename}</span>
          <span className="tnum block font-mono text-12 text-ink-500">
            {pageLabel(source.page_number)} · chunk {source.chunk_index} · score {formatScore(source.score)}
          </span>
        </span>
      </button>
      <p className={`mt-1.5 flex items-center gap-1.5 text-12 ${source.cited ? "text-accent-800" : "text-ink-500"}`}>
        {source.cited && <Quote aria-hidden="true" size={14} strokeWidth={1.75} />}
        {source.cited ? "Cited in the answer" : "Supplied to the model, not cited"}
      </p>
      <blockquote className="reading mt-1.5 text-ink-900 whitespace-pre-wrap">{source.excerpt}</blockquote>
      {selected && (
        <dl className="tnum mt-2 grid grid-cols-[auto_1fr] gap-x-3 font-mono text-12 text-ink-500">
          <dt>document</dt>
          <dd className="truncate" title={source.document_id}>{shortId(source.document_id)}</dd>
          {source.char_start !== null && source.char_end !== null && (
            <>
              <dt>characters</dt>
              <dd>{source.char_start}–{source.char_end} of the page text</dd>
            </>
          )}
        </dl>
      )}
    </li>
  );
}

function Summary({ response }: { response: QueryResponse }) {
  const e = response.evidence;
  return (
    <p className="tnum font-mono text-12 text-ink-500">
      {e.retrieved_count} retrieved · {e.supporting_count} at or above {formatScore(e.min_score_threshold)} · top-k {e.top_k}
      {e.max_score !== null && ` · best ${formatScore(e.max_score)}`}
    </p>
  );
}

export interface EvidencePanelProps {
  turn: Turn | null;
  selectedSourceId: string | null;
  onSelectSource: (sourceId: string) => void;
  onClose?: () => void;
}

export function EvidencePanel({ turn, selectedSourceId, onSelectSource, onClose }: EvidencePanelProps) {
  const response = turn?.state.kind === "done" ? turn.state.response : null;
  const ordered = response
    ? [...response.sources].sort((a, b) => Number(b.cited) - Number(a.cited))
    : [];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between gap-2 border-b border-paper-300 px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-14 font-medium text-ink-900">Evidence</h2>
          {turn && <p className="truncate text-12 text-ink-500" title={turn.question}>For: {turn.question}</p>}
        </div>
        {onClose && (
          <button type="button" onClick={onClose} aria-label="Close evidence panel" className="rounded-sm p-1.5 text-ink-500 hover:bg-paper-200 hover:text-ink-900">
            <X aria-hidden="true" size={16} strokeWidth={1.75} />
          </button>
        )}
      </div>
      <div className="flex-1 overflow-y-auto px-4 pb-6">
        {!turn && (
          <p className="py-4 text-13 text-ink-500">
            Passages behind an answer appear here, cited ones first, with document, page, and similarity
            score.
          </p>
        )}
        {turn && turn.state.kind === "pending" && <p className="py-4 text-13 text-ink-500">Waiting for the answer…</p>}
        {turn && turn.state.kind === "failed" && (
          <p className="py-4 text-13 text-ink-500">The request failed, so there is no evidence to show.</p>
        )}
        {response && response.status === "insufficient_evidence" && (
          <div className="space-y-2 py-4">
            <Summary response={response} />
            <p className="text-13 text-ink-500">
              No passage was used as evidence for this question. The API does not return passages that failed
              the evidence check.
            </p>
          </div>
        )}
        {response && response.status === "answered" && (
          <>
            <div className="py-3">
              <Summary response={response} />
              <p className="mt-0.5 text-12 text-ink-500">
                {plural(response.sources.filter((s) => s.cited).length, "passage")} cited of{" "}
                {response.sources.length} supplied to the model.
              </p>
            </div>
            <ol aria-label="Evidence passages">
              {ordered.map((source) => (
                <EvidenceItem
                  key={source.source_id}
                  source={source}
                  selected={source.source_id === selectedSourceId}
                  onSelect={() => onSelectSource(source.source_id)}
                />
              ))}
            </ol>
          </>
        )}
      </div>
    </div>
  );
}
