import {
  FileText,
  FlaskConical,
  GitCommitHorizontal,
  Menu,
  Monitor,
  Moon,
  RotateCw,
  ShieldCheck,
  Sun,
  X,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { StatusTag } from "../components/ui/StatusTag";
import type { ThemeChoice } from "../lib/browser";
import type { HealthState } from "./useHealth";
import type { View } from "./useRoute";

export interface NavItem {
  view: View;
  label: string;
  icon: LucideIcon;
  /** Stage in which the view gets a real data source; undefined when implemented. */
  plannedStage?: number;
}

// All four views read real backend data since Stage 5.5. The Pipeline view shows the
// pending CI/CD stages inside the view, so the item itself is not marked as planned.
export const NAV: NavItem[] = [
  { view: "workspace", label: "Workspace", icon: FileText },
  { view: "evaluation", label: "Evaluation", icon: ShieldCheck },
  { view: "experiments", label: "Experiments", icon: FlaskConical },
  { view: "pipeline", label: "Pipeline", icon: GitCommitHorizontal },
];

function BrandMark() {
  return (
    <svg viewBox="0 0 32 32" width="24" height="24" aria-hidden="true" className="shrink-0">
      <rect width="32" height="32" rx="6" fill="var(--ink-900)" />
      <rect x="8" y="7" width="16" height="3" rx="1" fill="var(--paper-100)" />
      <rect x="8" y="13" width="16" height="4" rx="1" fill="var(--accent-500)" />
      <rect x="8" y="20" width="11" height="3" rx="1" fill="var(--paper-100)" />
    </svg>
  );
}

function NavLinks({ current, expanded, onNavigate }: { current: View; expanded: boolean; onNavigate?: () => void }) {
  return (
    <ul className="space-y-0.5">
      {NAV.map((item) => {
        const active = item.view === current;
        const planned = item.plannedStage !== undefined ? `Planned, stage ${item.plannedStage}` : null;
        return (
          <li key={item.view}>
            <a
              href={`#/${item.view}`}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              aria-label={planned ? `${item.label} (${planned.toLowerCase()})` : item.label}
              title={planned ? `${item.label} — ${planned.toLowerCase()}` : item.label}
              className={`relative flex h-10 items-center gap-3 rounded-sm px-3 text-14 ${
                active ? "bg-paper-200 font-medium text-ink-900" : "text-ink-700 hover:bg-paper-200 hover:text-ink-900"
              } ${expanded ? "" : "justify-center px-0 xl:justify-start xl:px-3"}`}
            >
              {active && <span aria-hidden="true" className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-ink-900" />}
              <item.icon aria-hidden="true" size={20} strokeWidth={1.5} className="shrink-0" />
              <span className={expanded ? "flex-1" : "hidden flex-1 xl:inline"}>{item.label}</span>
              {item.plannedStage !== undefined && (
                <span className={`font-mono text-12 text-ink-500 ${expanded ? "" : "hidden xl:inline"}`}>planned</span>
              )}
            </a>
          </li>
        );
      })}
    </ul>
  );
}

export function NavRail({ current }: { current: View }) {
  return (
    <nav
      aria-label="Primary"
      className="hidden w-16 shrink-0 flex-col border-r border-paper-300 bg-paper-50 px-2 py-3 md:flex xl:w-[216px]"
    >
      <div className="mb-5 flex h-8 items-center justify-center gap-2 xl:justify-start xl:px-3">
        <BrandMark />
        <span className="hidden text-14 font-semibold tracking-tight text-ink-900 xl:inline">RAGGuard</span>
      </div>
      <NavLinks current={current} expanded={false} />
    </nav>
  );
}

export function BackendStatus({ health }: { health: HealthState }) {
  const { data, error, loading } = health;
  if (error) {
    return (
      <span title={error.message}>
        <StatusTag tone="fail">Backend unreachable</StatusTag>
      </span>
    );
  }
  if (!data) return <StatusTag tone={loading ? "loading" : "pending"}>Checking backend…</StatusTag>;
  const model = `${data.config.generation_model ?? "unknown model"} · ${data.config.generation_provider ?? "?"}`;
  if (data.status === "ok") {
    return (
      <span className="inline-flex items-center gap-2" title={`Generation: ${data.components.generation?.detail ?? ""}`}>
        <StatusTag tone="pass">Backend connected</StatusTag>
        <span className="hidden font-mono text-12 text-ink-500 lg:inline">{model}</span>
      </span>
    );
  }
  const store = data.components.vector_store;
  const label = !data.generation_ready ? "Generation unavailable" : store?.status !== "ok" ? "Vector store unavailable" : "Degraded";
  const detail = !data.generation_ready ? data.components.generation?.detail : store?.detail;
  return (
    <span title={detail}>
      <StatusTag tone="warn">{label}</StatusTag>
    </span>
  );
}

const THEMES: { value: ThemeChoice; label: string; icon: LucideIcon }[] = [
  { value: "system", label: "System theme", icon: Monitor },
  { value: "light", label: "Light theme", icon: Sun },
  { value: "dark", label: "Dark theme", icon: Moon },
];

export function TopBar({
  title,
  current,
  health,
  theme,
  onTheme,
}: {
  title: string;
  current: View;
  health: HealthState;
  theme: ThemeChoice;
  onTheme: (t: ThemeChoice) => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const collection = health.data?.config.qdrant_collection;
  return (
    <header className="relative border-b border-paper-300 bg-paper-50">
      <div className="flex h-14 items-center gap-3 px-4">
        <button
          type="button"
          className="rounded-sm p-1.5 text-ink-700 hover:bg-paper-200 md:hidden"
          aria-label={menuOpen ? "Close navigation" : "Open navigation"}
          aria-expanded={menuOpen}
          aria-controls="mobile-nav"
          onClick={() => setMenuOpen(!menuOpen)}
        >
          {menuOpen ? <X aria-hidden="true" size={20} /> : <Menu aria-hidden="true" size={20} />}
        </button>
        <div className="min-w-0 flex-1">
          <h1 id="view-title" tabIndex={-1} className="truncate text-18 font-semibold text-ink-900">{title}</h1>
          {collection && (
            <p className="hidden truncate font-mono text-12 text-ink-500 sm:block">collection {String(collection)}</p>
          )}
        </div>
        <div className="flex items-center gap-1 sm:gap-2">
          <BackendStatus health={health} />
          <button
            type="button"
            onClick={() => void health.refresh()}
            aria-label="Check backend status again"
            title="Check backend status again"
            className="rounded-sm p-1.5 text-ink-500 hover:bg-paper-200 hover:text-ink-900"
          >
            <RotateCw aria-hidden="true" size={16} strokeWidth={1.75} className={health.loading ? "animate-spin" : undefined} />
          </button>
          <div role="group" aria-label="Colour theme" className="hidden items-center rounded-sm border border-paper-300 sm:flex">
            {THEMES.map((t) => (
              <button
                key={t.value}
                type="button"
                aria-label={t.label}
                aria-pressed={theme === t.value}
                title={t.label}
                onClick={() => onTheme(t.value)}
                className={`p-1.5 ${theme === t.value ? "bg-paper-200 text-ink-900" : "text-ink-500 hover:text-ink-900"}`}
              >
                <t.icon aria-hidden="true" size={16} strokeWidth={1.75} />
              </button>
            ))}
          </div>
        </div>
      </div>
      {menuOpen && (
        <nav id="mobile-nav" aria-label="Primary" className="border-t border-paper-300 bg-paper-50 px-2 py-2 shadow-raised md:hidden">
          <NavLinks current={current} expanded onNavigate={() => setMenuOpen(false)} />
          <div role="group" aria-label="Colour theme" className="mt-2 flex gap-1 border-t border-paper-300 px-1 pt-2">
            {THEMES.map((t) => (
              <button
                key={t.value}
                type="button"
                aria-pressed={theme === t.value}
                onClick={() => onTheme(t.value)}
                className={`inline-flex items-center gap-1.5 rounded-sm px-2 py-1.5 text-13 ${theme === t.value ? "bg-paper-200 text-ink-900" : "text-ink-700"}`}
              >
                <t.icon aria-hidden="true" size={16} strokeWidth={1.75} />
                {t.label.replace(" theme", "")}
              </button>
            ))}
          </div>
        </nav>
      )}
    </header>
  );
}
