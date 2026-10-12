import { Fragment, useMemo } from "react";
import { pageLabel } from "../../lib/format";
import type { SourceReference } from "../../types/api";
import { parseAnswer, type Segment } from "./parseAnswer";

function Segments({
  segments,
  sources,
  selectedSourceId,
  onCite,
}: {
  segments: Segment[];
  sources: Map<string, SourceReference>;
  selectedSourceId: string | null;
  onCite: (sourceId: string) => void;
}) {
  return (
    <>
      {segments.map((segment, i) => {
        if (segment.type === "text") return <Fragment key={i}>{segment.text}</Fragment>;
        if (segment.type === "strong") return <strong key={i} className="font-semibold">{segment.text}</strong>;
        const source = sources.get(segment.sourceId)!;
        const selected = selectedSourceId === segment.sourceId;
        return (
          <button
            key={i}
            type="button"
            onClick={() => onCite(segment.sourceId)}
            aria-pressed={selected}
            aria-label={`Source ${segment.sourceId}: ${source.filename}, ${pageLabel(source.page_number)}`}
            title={`${source.filename} · ${pageLabel(source.page_number)}`}
            className={`mx-0.5 inline-flex -translate-y-1 items-center rounded-xs border px-1 align-baseline font-mono text-12 leading-4 transition-colors duration-150 ${
              selected
                ? "border-accent-500 bg-accent-300 text-on-accent"
                : "border-paper-300 bg-paper-200 text-ink-700 hover:border-accent-500"
            }`}
          >
            {segment.sourceId}
          </button>
        );
      })}
    </>
  );
}

export function AnswerText({
  answer,
  sources,
  selectedSourceId,
  onCite,
}: {
  answer: string;
  sources: SourceReference[];
  selectedSourceId: string | null;
  onCite: (sourceId: string) => void;
}) {
  const byId = useMemo(() => new Map(sources.map((s) => [s.source_id, s])), [sources]);
  const blocks = useMemo(() => parseAnswer(answer, new Set(byId.keys())), [answer, byId]);
  const shared = { sources: byId, selectedSourceId, onCite };

  return (
    <div className="max-w-[70ch] space-y-3 text-14 leading-6 text-ink-900">
      {blocks.map((block, i) => {
        if (block.type === "list") {
          const List = block.ordered ? "ol" : "ul";
          return (
            <List key={i} className={`space-y-1 pl-5 ${block.ordered ? "list-decimal" : "list-disc"} marker:text-ink-500`}>
              {block.items.map((item, j) => (
                <li key={j}>
                  <Segments segments={item} {...shared} />
                </li>
              ))}
            </List>
          );
        }
        if (block.interpretation) {
          return (
            <div key={i} className="border-l border-line-strong pl-3 text-ink-700">
              <span className="section-label mr-2">Interpretation</span>
              <Segments segments={block.segments} {...shared} />
            </div>
          );
        }
        return (
          <p key={i}>
            <Segments segments={block.segments} {...shared} />
          </p>
        );
      })}
    </div>
  );
}
