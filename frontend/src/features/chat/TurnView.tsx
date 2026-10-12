import { PanelRight, RotateCw, SearchX, Waypoints } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "../../components/ui/Button";
import { InlineAlert } from "../../components/ui/InlineAlert";
import { StatusTag } from "../../components/ui/StatusTag";
import { formatMs, formatScore, pageLabel, plural } from "../../lib/format";
import type { QueryResponse } from "../../types/api";
import { AnswerText } from "./AnswerText";
import type { Turn } from "./useConversation";

export function fallbackExplanation(response: QueryResponse, scoped: boolean): string {
  const { evidence, generation } = response;
  const threshold = formatScore(evidence.min_score_threshold);
  switch (response.fallback_reason) {
    case "no_results":
      return `No passages were retrieved${scoped ? " from the selected documents" : ""}. The model was not called.`;
    case "below_threshold":
      return `${plural(evidence.retrieved_count, "passage")} retrieved; the closest scored ${formatScore(evidence.max_score ?? 0)}, below the ${threshold} evidence threshold. The model was not called.`;
    case "model_declined":
      return `${plural(evidence.supporting_count, "passage")} passed the ${threshold} similarity threshold, but the model${generation ? ` (${generation.model})` : ""} judged that they do not answer the question.`;
    default:
      return "The backend reported insufficient evidence.";
  }
}

function TimingStrip({ response }: { response: QueryResponse }) {
  const { latency_ms: l, generation } = response;
  const parts = [
    `embedding ${formatMs(l.embedding_ms)}`,
    `retrieval ${formatMs(l.retrieval_ms)}`,
    l.generation_ms !== null ? `generation ${formatMs(l.generation_ms)}` : "no generation",
    `total ${formatMs(l.total_ms)}`,
  ];
  return (
    <p className="tnum font-mono text-12 text-ink-500">
      {parts.join(" · ")}
      {generation && (
        <>
          {" "}· {generation.model} via {generation.provider} · prompt {generation.prompt_version}
        </>
      )}
    </p>
  );
}

export interface TurnViewProps {
  turn: Turn;
  selected: boolean;
  selectedSourceId: string | null;
  traceOpen: boolean;
  onCite: (sourceId: string) => void;
  onShowEvidence: () => void;
  onToggleTrace: () => void;
  onRetry: () => void;
  trace: ReactNode;
}

export function TurnView({
  turn,
  selected,
  selectedSourceId,
  traceOpen,
  onCite,
  onShowEvidence,
  onToggleTrace,
  onRetry,
  trace,
}: TurnViewProps) {
  const scopeText = turn.scope ? `Limited to ${turn.scopeNames.join(", ")}` : "All indexed documents";
  const { state } = turn;

  return (
    <article
      aria-label={`Question: ${turn.question}`}
      className={`border-l-2 py-1 pl-4 ${selected ? "border-l-ink-900" : "border-l-paper-300"}`}
    >
      <header className="mb-3">
        <p className="section-label">Question</p>
        <p className="mt-0.5 text-16 leading-6 font-medium whitespace-pre-wrap text-ink-900">{turn.question}</p>
        <p className="mt-0.5 truncate text-12 text-ink-500" title={scopeText}>{scopeText}</p>
      </header>

      {state.kind === "pending" && (
        <div aria-live="polite">
          <StatusTag tone="loading">Retrieving evidence and waiting for the answer…</StatusTag>
          <p className="mt-1 text-12 text-ink-500">Local generation usually takes a few seconds.</p>
        </div>
      )}

      {state.kind === "failed" && (
        <InlineAlert
          tone="error"
          title="Request failed — no answer was produced"
          action={<Button size="sm" icon={RotateCw} onClick={onRetry}>Retry</Button>}
        >
          {state.error.message}
          {state.error.code && <span className="ml-1 font-mono text-12">({state.error.code})</span>}
          {state.error.status !== null && !state.error.code && (
            <span className="ml-1 font-mono text-12">(HTTP {state.error.status})</span>
          )}
        </InlineAlert>
      )}

      {state.kind === "done" && state.response.status === "insufficient_evidence" && (
        <section
          aria-label="Insufficient evidence"
          className="rounded-md border border-paper-300 bg-paper-50 px-4 py-3"
        >
          <div className="flex items-start gap-3">
            <SearchX aria-hidden="true" size={20} strokeWidth={1.5} className="mt-0.5 shrink-0 text-ink-500" />
            <div className="min-w-0 space-y-1.5">
              <p className="text-14 font-medium text-ink-900">Not enough evidence to answer</p>
              <p className="text-14 text-ink-700">{state.response.answer}</p>
              <p className="tnum text-13 text-ink-500">{fallbackExplanation(state.response, turn.scope !== null)}</p>
              <p className="text-12 text-ink-500">
                No passages are shown: the API does not return passages that failed the evidence check.
              </p>
            </div>
          </div>
          <div className="mt-3"><TimingStrip response={state.response} /></div>
        </section>
      )}

      {state.kind === "done" && state.response.status === "answered" && (
        <section aria-label="Answer" className="space-y-3">
          <AnswerText
            answer={state.response.answer}
            sources={state.response.sources}
            selectedSourceId={selected ? selectedSourceId : null}
            onCite={onCite}
          />
          <CitedSources response={state.response} onCite={onCite} />
          <TimingStrip response={state.response} />
          <div className="flex flex-wrap gap-2">
            <Button size="sm" icon={Waypoints} aria-expanded={traceOpen} onClick={onToggleTrace}>
              {traceOpen ? "Hide evidence trace" : "Trace this answer"}
            </Button>
            <Button size="sm" variant="ghost" icon={PanelRight} onClick={onShowEvidence} className="xl:hidden">
              Show evidence
            </Button>
          </div>
          {traceOpen && trace}
        </section>
      )}
    </article>
  );
}

function CitedSources({ response, onCite }: { response: QueryResponse; onCite: (id: string) => void }) {
  const cited = response.sources.filter((s) => s.cited);
  if (cited.length === 0) {
    return (
      <p className="text-13 text-ink-500">
        The answer does not reference any source ID.{" "}
        {plural(response.sources.length, "passage")} {response.sources.length === 1 ? "was" : "were"} supplied
        to the model as evidence; see the evidence panel.
      </p>
    );
  }
  return (
    <div>
      <p className="section-label mb-1">Cited sources</p>
      <ul className="space-y-0.5">
        {cited.map((s) => (
          <li key={s.source_id} className="text-13 text-ink-700">
            <button
              type="button"
              onClick={() => onCite(s.source_id)}
              className="rounded-xs text-left hover:text-ink-900 hover:underline"
            >
              <span className="font-mono text-12 text-ink-500">{s.source_id}</span>{" "}
              {s.filename} <span className="text-ink-500">· {pageLabel(s.page_number)}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
