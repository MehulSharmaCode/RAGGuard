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
        // One superscript group per run of adjacent markers: "[S1, S2]". The brackets and
        // separators are text, so copying the answer keeps readable citations.
        return (
          <sup key={i} className="mx-0.5 font-mono text-12 leading-none whitespace-nowrap text-ink-500">
            [
            {segment.sourceIds.map((id, j) => {
              const source = sources.get(id)!;
              const selected = selectedSourceId === id;
              return (
                <Fragment key={id}>
                  {j > 0 && ", "}
                  <button
                    type="button"
                    onClick={() => onCite(id)}
                    aria-pressed={selected}
                    aria-label={`Source ${id}: ${source.filename}, ${pageLabel(source.page_number)}`}
                    title={`${source.filename} · ${pageLabel(source.page_number)}`}
                    className={`rounded-xs px-0.5 underline decoration-dotted underline-offset-2 transition-colors duration-150 ${
                      selected ? "bg-accent-300 text-on-accent" : "text-accent-800 hover:bg-paper-200"
                    }`}
                  >
                    {id}
                  </button>
                </Fragment>
              );
            })}
            ]
          </sup>
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
