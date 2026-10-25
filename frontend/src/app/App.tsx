import { lazy, Suspense, useEffect, useRef } from "react";
import { ConversationProvider } from "../features/chat/ConversationProvider";
import { useTheme } from "../lib/browser";
import { NavRail, TopBar } from "./Shell";
import { useHealth } from "./useHealth";
import { useRoute } from "./useRoute";
import { Workspace } from "./Workspace";

// Data views are code-split (UI_DESIGN_SPEC §13): the Workspace never waits for them.
const EvaluationView = lazy(() => import("../features/evaluation/EvaluationView"));
const ExperimentsView = lazy(() => import("../features/experiments/ExperimentsView"));
const PipelineView = lazy(() => import("../features/pipeline/PipelineView"));

const TITLES: Record<string, string> = {
  workspace: "Document workspace",
  evaluation: "Evaluation",
  experiments: "Experiments",
  pipeline: "Pipeline",
};

function ViewLoading() {
  return (
    <p className="px-6 py-8 text-13 text-ink-500" aria-busy="true">
      Loading view…
    </p>
  );
}

export function App() {
  const { view, param } = useRoute();
  const health = useHealth();
  const [theme, setTheme] = useTheme();
  const previousView = useRef(view);

  // After in-app navigation (not on first load), move focus to the new view's heading.
  useEffect(() => {
    if (previousView.current === view) return;
    previousView.current = view;
    document.getElementById("view-title")?.focus();
  }, [view]);

  useEffect(() => {
    document.title = `${TITLES[view]} · RAGGuard`;
  }, [view]);

  return (
    <ConversationProvider>
      <div className="flex h-full bg-paper-100 text-ink-900">
        <a
          href="#main"
          onClick={(event) => {
            event.preventDefault();
            document.getElementById("main")?.focus();
          }}
          className="sr-only z-50 rounded-sm bg-ink-900 px-3 py-2 text-paper-50 focus:not-sr-only focus:absolute focus:top-2 focus:left-2"
        >
          Skip to main content
        </a>
        <NavRail current={view} />
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar title={TITLES[view] ?? "RAGGuard"} current={view} health={health} theme={theme} onTheme={setTheme} />
          <main id="main" tabIndex={-1} className="min-h-0 flex-1 overflow-y-auto outline-none">
            <Suspense fallback={<ViewLoading />}>
              {view === "workspace" && <Workspace health={health} />}
              {view === "evaluation" && <EvaluationView runId={param} />}
              {view === "experiments" && <ExperimentsView />}
              {view === "pipeline" && <PipelineView />}
            </Suspense>
          </main>
        </div>
      </div>
    </ConversationProvider>
  );
}
