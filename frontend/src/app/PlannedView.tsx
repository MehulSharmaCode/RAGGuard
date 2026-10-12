import { CircleDashed } from "lucide-react";
import { NAV } from "./Shell";
import type { View } from "./useRoute";

const COPY: Record<Exclude<View, "workspace">, { empty: string; detail: string }> = {
  evaluation: {
    empty: "No evaluation runs yet. Runs appear here after the evaluation suite is executed locally or in CI.",
    detail:
      "The fixed evaluation dataset, metrics, and runner are built in Stage 4. Until then this view has no data source, so it shows nothing rather than sample numbers.",
  },
  experiments: {
    empty: "No tracked experiments yet. Runs appear here once evaluation runs are logged to MLflow.",
    detail: "Comparing configurations and metrics across tracked runs is built in Stage 5.",
  },
  pipeline: {
    empty: "CI integration not configured yet.",
    detail:
      "Test and quality-gate results for code changes appear here once the GitHub Actions gate exists (Stage 7). No workflow runs are simulated.",
  },
};

/** Honest placeholder for destinations whose data sources do not exist yet. */
export function PlannedView({ view }: { view: Exclude<View, "workspace"> }) {
  const item = NAV.find((n) => n.view === view)!;
  const copy = COPY[view];
  return (
    <div className="mx-auto max-w-[640px] px-6 py-16">
      <p className="section-label inline-flex items-center gap-1.5">
        <CircleDashed aria-hidden="true" size={14} strokeWidth={1.75} />
        Planned · Stage {item.plannedStage}
      </p>
      <p className="mt-3 text-16 leading-6 text-ink-900">{copy.empty}</p>
      <p className="mt-2 text-14 text-ink-700">{copy.detail}</p>
      <p className="mt-6 text-13">
        <a href="#/workspace" className="text-accent-800 underline underline-offset-2 hover:text-ink-900">
          Go to the document workspace
        </a>
      </p>
    </div>
  );
}
