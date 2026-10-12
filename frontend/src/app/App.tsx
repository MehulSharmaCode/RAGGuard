import { useEffect, useRef } from "react";
import { useTheme } from "../lib/browser";
import { PlannedView } from "./PlannedView";
import { NavRail, TopBar } from "./Shell";
import { useHealth } from "./useHealth";
import { useRoute } from "./useRoute";
import { Workspace } from "./Workspace";

const TITLES: Record<string, string> = {
  workspace: "Document workspace",
  evaluation: "Evaluation",
  experiments: "Experiments",
  pipeline: "Pipeline status",
};

export function App() {
  const view = useRoute();
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
          {view === "workspace" ? (
            <Workspace health={health} />
          ) : (
            <PlannedView view={view} />
          )}
        </main>
      </div>
    </div>
  );
}

