/**
 * "Trace this answer": the Evidence Trace bound to one real query response.
 * The HTML stepper drives the scene and is fully keyboard operable; the stage panel
 * is the text equivalent of the (aria-hidden) scene.
 */

import { Box, Layers3 } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { formatMs, formatScore, pageLabel, plural } from "../../../lib/format";
import type { DocumentInfo, QueryResponse } from "../../../types/api";
import { computeLayout, type SceneInput } from "./layout";
import { SceneView, useSceneMode } from "./SceneView";
import { buildTraceModel, STAGES, type StageIndex, type TraceModel } from "./traceModel";

export function toSceneInput(model: TraceModel): SceneInput {
  return {
    documents: model.documents.map((d) => ({
      totalPages: d.totalPages,
      chunkCount: d.chunkCount,
      retrieved: d.retrieved.map((r) => ({ key: r.sourceId, page: r.pageNumber, chunkIndex: r.chunkIndex })),
    })),
    evidence: model.evidence.map((e) => ({
      key: e.sourceId,
      documentIndex: e.documentIndex,
      cited: e.cited,
      strength: e.score,
    })),
  };
}

function stageSummary(model: TraceModel, stage: StageIndex): string {
  const sources = model.evidence.length;
  switch (stage) {
    case 0:
      return plural(model.documents.length, "document");
    case 1:
      return `${sources} highlighted`;
    case 2:
      return `${sources} supplied`;
    case 3:
      return `cites ${model.citedCount}`;
  }
}

export interface EvidenceTraceProps {
  response: QueryResponse;
  documents: DocumentInfo[] | null;
  selectedSourceId: string | null;
  onSelectSource: (sourceId: string) => void;
}

export function EvidenceTrace({ response, documents, selectedSourceId, onSelectSource }: EvidenceTraceProps) {
  const model = useMemo(() => buildTraceModel(response, documents), [response, documents]);
  const layout = useMemo(() => computeLayout(toSceneInput(model)), [model]);
  const [stage, setStage] = useState<StageIndex>(2);
  const { mode, unavailableReason, prefer2D, setPrefer2D } = useSceneMode();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const baseId = useId();
  const sectionRef = useRef<HTMLElement>(null);

  useEffect(() => {
    sectionRef.current?.scrollIntoView?.({ block: "nearest" });
  }, []);

  const go = (next: number) => {
    const target = ((next + STAGES.length) % STAGES.length) as StageIndex;
    setStage(target);
    tabRefs.current[target]?.focus();
  };
  const onTabKey = (event: KeyboardEvent) => {
    const keys: Record<string, () => void> = {
      ArrowRight: () => go(stage + 1),
      ArrowDown: () => go(stage + 1),
      ArrowLeft: () => go(stage - 1),
      ArrowUp: () => go(stage - 1),
      Home: () => go(0),
      End: () => go(STAGES.length - 1),
    };
    const action = keys[event.key];
    if (action) {
      event.preventDefault();
      action();
    }
  };

  return (
    <section ref={sectionRef} aria-label="Evidence trace" className="rounded-md border border-paper-300 bg-paper-50">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-paper-300 px-3 py-2">
        <p className="section-label">Evidence trace</p>
        <div className="flex items-center gap-2 text-12 text-ink-500">
          {unavailableReason ? (
            <span>{unavailableReason}</span>
          ) : (
            <button
              type="button"
              onClick={() => setPrefer2D(!prefer2D)}
              className="inline-flex items-center gap-1 rounded-xs px-1.5 py-1 text-ink-700 hover:bg-paper-200"
            >
              {prefer2D ? <Layers3 aria-hidden="true" size={14} /> : <Box aria-hidden="true" size={14} />}
              {prefer2D ? "Show 3D view" : "Show 2D view"}
            </button>
          )}
        </div>
      </div>

      <div role="tablist" aria-label="Trace stages" className="grid grid-cols-2 border-b border-paper-300 sm:grid-cols-4">
        {STAGES.map((name, i) => {
          const selected = stage === i;
          return (
            <button
              key={name}
              ref={(el) => {
                tabRefs.current[i] = el;
              }}
              role="tab"
              id={`${baseId}-tab-${i}`}
              aria-selected={selected}
              aria-controls={`${baseId}-panel`}
              tabIndex={selected ? 0 : -1}
              onClick={() => setStage(i as StageIndex)}
              onKeyDown={onTabKey}
              className={`border-b-2 px-3 py-2 text-left ${
                selected ? "border-b-ink-900 bg-paper-100" : "border-b-transparent hover:bg-paper-100"
              }`}
            >
              <span className="block text-13 font-medium text-ink-900">
                <span className="font-mono text-12 text-ink-500">{i + 1}</span> {name}
              </span>
              <span className="tnum block font-mono text-12 text-ink-500">{stageSummary(model, i as StageIndex)}</span>
            </button>
          );
        })}
      </div>

      <div className="h-56 border-b border-paper-300 md:h-64">
        <SceneView
          mode={mode}
          layout={layout}
          selectedKey={selectedSourceId}
          activeStage={stage}
          onSelect={onSelectSource}
        />
      </div>

      <div
        role="tabpanel"
        id={`${baseId}-panel`}
        aria-labelledby={`${baseId}-tab-${stage}`}
        className="px-3 py-3 text-13 text-ink-700"
      >
        <StagePanel model={model} stage={stage} selectedSourceId={selectedSourceId} onSelectSource={onSelectSource} />
      </div>

      <p className="border-t border-paper-300 px-3 py-2 text-12 text-ink-500">
        Built from this response and the document list. It shows which passages were supplied to the model
        and which the answer cites — it explains the evidence path, it does not prove the answer is correct.
      </p>
    </section>
  );
}

function StagePanel({
  model,
  stage,
  selectedSourceId,
  onSelectSource,
}: {
  model: TraceModel;
  stage: StageIndex;
  selectedSourceId: string | null;
  onSelectSource: (id: string) => void;
}) {
  const { response } = model;
  if (stage === 0) {
    return (
      <ul className="space-y-1.5">
        {model.documents.map((d) => {
          const pages = [...new Set(d.retrieved.map((r) => r.pageNumber))];
          return (
            <li key={d.documentId}>
              <span className="text-ink-900">{d.filename}</span>{" "}
              <span className="tnum font-mono text-12 text-ink-500">
                {d.listed
                  ? `${d.fileType?.toUpperCase()} · ${d.totalPages !== null ? plural(d.totalPages, "page") : "no page numbers"}`
                  : "no longer in the document list; totals unknown"}
              </span>
              <span className="block text-12 text-ink-500">
                Evidence from{" "}
                {pages.every((p) => p === null)
                  ? "a file without page numbers"
                  : pages.filter((p): p is number => p !== null).map((p) => `p. ${p}`).join(", ")}
              </span>
            </li>
          );
        })}
      </ul>
    );
  }
  if (stage === 1) {
    return (
      <ul className="space-y-1.5">
        {model.documents.map((d) => (
          <li key={d.documentId}>
            <span className="text-ink-900">{d.filename}</span>{" "}
            <span className="tnum font-mono text-12 text-ink-500">
              {d.chunkCount !== null ? `${plural(d.chunkCount, "chunk")} indexed` : "chunk total unknown"} · evidence
              from chunk {d.retrieved.map((r) => r.chunkIndex).sort((a, b) => a - b).join(", ")}
            </span>
          </li>
        ))}
        <li className="text-12 text-ink-500">
          Highlighted strips are the chunks supplied as evidence (retrieved and at or above the score
          threshold), in document order. Large documents are drawn scaled: one strip or page tile can stand
          for several.
        </li>
      </ul>
    );
  }
  if (stage === 2) {
    return (
      <div>
        <p className="tnum mb-2 font-mono text-12 text-ink-500">
          {response.evidence.retrieved_count} retrieved · {response.evidence.supporting_count} at or above{" "}
          {formatScore(response.evidence.min_score_threshold)} · top-k {response.evidence.top_k}
        </p>
        <ol aria-label="Evidence nodes" className="space-y-1">
          {model.evidence.map((e) => {
            const selected = e.sourceId === selectedSourceId;
            return (
              <li key={e.sourceId}>
                <button
                  type="button"
                  aria-pressed={selected}
                  onClick={() => onSelectSource(e.sourceId)}
                  className={`flex w-full items-baseline gap-2 rounded-xs border-l-2 px-2 py-1 text-left ${
                    selected ? "border-l-accent-500 bg-paper-100" : "border-l-transparent hover:bg-paper-100"
                  }`}
                >
                  <span className="font-mono text-12 text-ink-500">{e.sourceId}</span>
                  <span className="min-w-0 flex-1 truncate text-ink-900">
                    {e.filename} <span className="text-ink-500">· {pageLabel(e.pageNumber)} · chunk {e.chunkIndex}</span>
                  </span>
                  <span className="tnum font-mono text-12 text-ink-500">{formatScore(e.score)}</span>
                  <span className={`text-12 ${e.cited ? "text-accent-800" : "text-ink-500"}`}>
                    {e.cited ? "cited" : "not cited"}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </div>
    );
  }
  return (
    <div className="space-y-1">
      <p>
        {model.citedCount > 0
          ? `The answer cites ${model.evidence.filter((e) => e.cited).map((e) => e.sourceId).join(", ")}; only those are linked to the answer.`
          : "The answer does not cite any source ID, so no evidence is linked to it."}
      </p>
      {response.generation && (
        <p className="tnum font-mono text-12 text-ink-500">
          {response.generation.model} via {response.generation.provider} · prompt {response.generation.prompt_version}
          {response.latency_ms.generation_ms !== null && ` · generation ${formatMs(response.latency_ms.generation_ms)}`}
        </p>
      )}
    </div>
  );
}
