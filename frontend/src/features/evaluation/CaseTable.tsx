import { ChevronDown, ChevronRight, Search } from "lucide-react";
import { Fragment, useId, useMemo, useState, type ReactNode } from "react";
import { fieldClass } from "../../components/data/Section";
import { StatusTag, type Tone } from "../../components/ui/StatusTag";
import { formatMs, formatScore, pageLabel, plural } from "../../lib/format";
import type { CaseVerdict, CaseView, FindingKind } from "../../types/api";
import { categoryLabel, FALLBACK_TEXT, FINDING_GROUPS, FINDING_LABELS } from "./labels";

export type VerdictFilter = "fail" | "pass" | "error" | "unscored" | "findings" | "all";

export interface CaseFilters {
  verdict: VerdictFilter;
  category: string;
  finding: FindingKind | "any";
  search: string;
}

export const VERDICT_TONE: Record<CaseVerdict, { tone: Tone; label: string }> = {
  pass: { tone: "pass", label: "Passed" },
  fail: { tone: "fail", label: "Failed" },
  error: { tone: "warn", label: "Error" },
  unscored: { tone: "pending", label: "No verdict" },
};

function matches(c: CaseView, f: CaseFilters): boolean {
  if (f.verdict === "findings" ? c.findings.length === 0 : f.verdict !== "all" && c.verdict !== f.verdict) return false;
  if (f.category !== "all" && c.category !== f.category) return false;
  if (f.finding !== "any" && !c.findings.some((x) => x.kind === f.finding)) return false;
  const q = f.search.trim().toLowerCase();
  return !q || c.case_id.toLowerCase().includes(q) || c.question.toLowerCase().includes(q);
}

function outcomeText(c: CaseView): string {
  if (c.outcome === "fallback") return `Fallback · ${c.fallback_reason ?? "unknown reason"}`;
  if (c.outcome === "answered") return "Answered";
  if (c.outcome === "error") return "Pipeline error";
  return c.outcome ?? "—";
}

export function CaseTable({
  cases,
  filters,
  onFilters,
}: {
  cases: CaseView[];
  filters: CaseFilters;
  onFilters: (f: CaseFilters) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const ids = useId();
  const shown = useMemo(() => cases.filter((c) => matches(c, filters)), [cases, filters]);
  const count = (fn: (c: CaseView) => boolean) => cases.filter(fn).length;
  const categories = [...new Set(cases.map((c) => c.category))].sort();
  const present = new Set(cases.flatMap((c) => c.findings.map((f) => f.kind)));
  const set = (patch: Partial<CaseFilters>) => onFilters({ ...filters, ...patch });

  const verdictOptions: { value: VerdictFilter; label: string; n: number }[] = [
    { value: "fail", label: "Failed", n: count((c) => c.verdict === "fail") },
    { value: "findings", label: "With findings", n: count((c) => c.findings.length > 0) },
    { value: "pass", label: "Passed", n: count((c) => c.verdict === "pass") },
    { value: "error", label: "Errors", n: count((c) => c.verdict === "error") },
    { value: "unscored", label: "No verdict", n: count((c) => c.verdict === "unscored") },
    { value: "all", label: "All cases", n: cases.length },
  ];

  return (
    <div>
      <div role="group" aria-label="Filter cases" className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-12 text-ink-500">
          Show
          <select name="verdict" className={fieldClass} value={filters.verdict} onChange={(e) => set({ verdict: e.target.value as VerdictFilter })}>
            {verdictOptions
              .filter((o) => o.n > 0 || o.value === filters.verdict || o.value === "fail" || o.value === "all")
              .map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label} ({o.n})
                </option>
              ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-12 text-ink-500">
          Category
          <select name="category" className={fieldClass} value={filters.category} onChange={(e) => set({ category: e.target.value })}>
            <option value="all">All categories</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {categoryLabel(c)} ({count((x) => x.category === c)})
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-12 text-ink-500">
          Finding
          <select name="finding" className={fieldClass} value={filters.finding} onChange={(e) => set({ finding: e.target.value as FindingKind | "any" })}>
            <option value="any">Any finding or none</option>
            {FINDING_GROUPS.map((g) => (
              <optgroup key={g.label} label={g.label}>
                {g.kinds
                  .filter((k) => present.has(k) || filters.finding === k)
                  .map((k) => (
                    <option key={k} value={k}>
                      {FINDING_LABELS[k]} ({count((c) => c.findings.some((f) => f.kind === k))})
                    </option>
                  ))}
              </optgroup>
            ))}
          </select>
        </label>
        <label className="flex min-w-[180px] flex-1 flex-col gap-1 text-12 text-ink-500">
          Search ID or question
          <span className="relative">
            <Search aria-hidden="true" size={14} className="pointer-events-none absolute top-2 left-2 text-ink-500" />
            <input
              type="search"
              name="case-search"
              className={`${fieldClass} w-full pl-7`}
              value={filters.search}
              onChange={(e) => set({ search: e.target.value })}
            />
          </span>
        </label>
      </div>
      <p className="tnum mt-2 text-12 text-ink-500" aria-live="polite">
        {shown.length} of {plural(cases.length, "case")} shown
      </p>

      {shown.length === 0 ? (
        <p className="mt-3 text-13 text-ink-700">No case matches these filters.</p>
      ) : (
        <div className="relative mt-2 overflow-x-auto border-y border-paper-300">
          <table className="w-full min-w-[760px] border-collapse text-13" aria-label="Evaluation cases">
            <thead className="sticky top-0 bg-paper-100 text-left text-12 text-ink-500">
              <tr className="border-b border-paper-300">
                <th scope="col" className="py-2 pr-2 pl-1 font-medium">Case</th>
                <th scope="col" className="py-2 pr-2 font-medium">Question</th>
                <th scope="col" className="py-2 pr-2 font-medium">Verdict</th>
                <th scope="col" className="py-2 pr-2 font-medium">Outcome</th>
                <th scope="col" className="py-2 pr-1 font-medium">Findings</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((c) => {
                const expanded = open === c.case_id;
                const detailId = `${ids}-${c.case_id}`;
                return (
                  <Fragment key={c.case_id}>
                    <tr className={`border-b border-paper-300 align-top ${expanded ? "bg-paper-50" : "hover:bg-paper-200"}`}>
                      <td className="py-2 pr-2 pl-1">
                        <button
                          type="button"
                          aria-expanded={expanded}
                          aria-controls={detailId}
                          onClick={() => setOpen(expanded ? null : c.case_id)}
                          className="inline-flex items-center gap-1 rounded-xs font-mono text-12 text-ink-900 hover:underline"
                        >
                          {expanded ? <ChevronDown aria-hidden="true" size={14} /> : <ChevronRight aria-hidden="true" size={14} />}
                          {c.case_id}
                          <span className="sr-only">: {expanded ? "hide" : "show"} details</span>
                        </button>
                        <span className="block pl-5 text-12 text-ink-500">{categoryLabel(c.category)}</span>
                      </td>
                      <td className="max-w-[360px] py-2 pr-2 text-ink-900">{c.question}</td>
                      <td className="py-2 pr-2 whitespace-nowrap">
                        <StatusTag tone={VERDICT_TONE[c.verdict].tone}>{VERDICT_TONE[c.verdict].label}</StatusTag>
                      </td>
                      <td className="py-2 pr-2 text-12 text-ink-700">{outcomeText(c)}</td>
                      <td className="py-2 pr-1 text-12 text-ink-700">
                        {c.findings.length === 0 ? (
                          <span className="text-ink-500">None</span>
                        ) : (
                          <ul>
                            {[...new Set(c.findings.map((f) => f.kind))].map((k) => (
                              <li key={k}>{FINDING_LABELS[k]}</li>
                            ))}
                          </ul>
                        )}
                      </td>
                    </tr>
                    {expanded && (
                      <tr id={detailId} className="border-b border-paper-300 bg-paper-50">
                        <td colSpan={5} className="px-3 py-4">
                          <CaseDetail c={c} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Facts({ c }: { c: CaseView }) {
  if (c.required_facts.length === 0) return null;
  const missing = new Set(c.facts_missing);
  const answered = c.outcome === "answered";
  return (
    <div>
      <p className="section-label">Required facts</p>
      <ul className="mt-1 space-y-0.5 text-13">
        {c.required_facts.map((f) => (
          <li key={f} className="flex items-center gap-2">
            {answered ? (
              <StatusTag tone={missing.has(f) ? "fail" : "pass"}>{missing.has(f) ? "Missing" : "Found"}</StatusTag>
            ) : (
              <StatusTag tone="pending">Not answered</StatusTag>
            )}
            <span className="text-ink-900">{f}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="section-label">{label}</p>
      <div className="mt-0.5 text-13 text-ink-900">{children}</div>
    </div>
  );
}

function yesNo(value: boolean | null): string {
  return value === null ? "n/a" : value ? "yes" : "no";
}

export function CaseDetail({ c }: { c: CaseView }) {
  return (
    <div className="space-y-5" aria-label={`Details of ${c.case_id}`}>
      <div className="grid gap-5 md:grid-cols-2">
        <div className="space-y-3">
          <h3 className="text-14 font-semibold text-ink-900">Expected</h3>
          <Field label="Label">{c.answerability === "answerable" ? "Answerable from the corpus" : "Unanswerable: the safe fallback is expected"}</Field>
          {c.reference_answer && (
            <Field label="Reference answer">
              <p className="reading whitespace-pre-wrap">{c.reference_answer}</p>
            </Field>
          )}
          {c.expected_sources.length > 0 && <Field label="Expected sources">{c.expected_sources.join(", ")}</Field>}
          {c.superseded_sources.length > 0 && (
            <Field label="Superseded (must not be cited for current facts)">{c.superseded_sources.join(", ")}</Field>
          )}
          <Facts c={c} />
        </div>
        <div className="space-y-3">
          <h3 className="text-14 font-semibold text-ink-900">Actual</h3>
          <Field label="Outcome">
            {c.outcome === "fallback"
              ? `Safe fallback — ${FALLBACK_TEXT[c.fallback_reason ?? ""] ?? c.fallback_reason ?? "reason not recorded"}`
              : outcomeText(c)}
            {c.llm_called !== null && <span className="text-ink-500"> · model {c.llm_called ? "called" : "not called"}</span>}
          </Field>
          {c.error && <Field label="Error">{c.error}</Field>}
          <Field label={c.outcome === "fallback" ? "Returned text" : "Answer"}>
            {c.answer ? <p className="reading whitespace-pre-wrap">{c.answer}</p> : <span className="text-ink-500">Not recorded.</span>}
          </Field>
          <Field label="Cited documents">
            {c.cited_filenames.length ? c.cited_filenames.join(", ") : <span className="text-ink-500">None</span>}
            {c.invalid_citation_ids.length > 0 && (
              <span className="block text-fail">Invalid IDs (not in the evidence): {c.invalid_citation_ids.join(", ")}</span>
            )}
          </Field>
          <p className="tnum font-mono text-12 text-ink-500">
            best score {c.max_score === null ? "n/a" : formatScore(c.max_score)} · {c.latency_ms === null ? "latency n/a" : formatMs(c.latency_ms)}
          </p>
        </div>
      </div>

      <div>
        <h3 className="text-14 font-semibold text-ink-900">Findings</h3>
        {c.findings.length === 0 ? (
          <p className="mt-1 text-13 text-ink-700">No problem was recorded for this case.</p>
        ) : (
          <ul className="mt-1 space-y-1 text-13">
            {c.findings.map((f, i) => (
              <li key={`${f.kind}-${i}`}>
                <span className="font-medium text-ink-900">{FINDING_LABELS[f.kind]}:</span> <span className="text-ink-700">{f.detail}</span>
              </li>
            ))}
          </ul>
        )}
        {c.diagnostic && <p className="mt-2 text-13 text-ink-700">Diagnostic: {c.diagnostic}</p>}
      </div>

      {c.attack && (
        <div>
          <h3 className="text-14 font-semibold text-ink-900">Prompt-injection attack</h3>
          <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-13">
            <dt className="text-ink-500">Result</dt>
            <dd>
              <StatusTag tone={c.attack.status === "succeeded" ? "fail" : c.attack.status === "blocked" ? "pass" : "warn"}>
                {c.attack.status === "succeeded" ? "Attack succeeded" : c.attack.status === "blocked" ? "Attack blocked" : c.attack.status}
              </StatusTag>
            </dd>
            <dt className="text-ink-500">Scenario</dt>
            <dd className="font-mono text-12">{c.attack.scenario_id}</dd>
            <dt className="text-ink-500">Vector / channel</dt>
            <dd>{categoryLabel(c.attack.vector)} · {c.attack.channel.replace(/_/g, " ")}</dd>
            {c.attack.reasons.length > 0 && (
              <>
                <dt className="text-ink-500">Why</dt>
                <dd>{c.attack.reasons.join("; ")}</dd>
              </>
            )}
            <dt className="text-ink-500">Canary leaked</dt>
            <dd>{yesNo(c.attack.canary_leaked)}</dd>
            <dt className="text-ink-500">Legitimate task done</dt>
            <dd>{yesNo(c.attack.task_completed)}</dd>
            {c.attack.echoed.length > 0 && (
              <>
                <dt className="text-ink-500">Echoed (not counted)</dt>
                <dd>{c.attack.echoed.join(", ")}</dd>
              </>
            )}
          </dl>
        </div>
      )}

      <div>
        <h3 className="text-14 font-semibold text-ink-900">Retrieved passages</h3>
        {c.retrieved.length === 0 ? (
          <p className="mt-1 text-13 text-ink-700">No passages were recorded.</p>
        ) : (
          <ol className="mt-1 space-y-2">
            {c.retrieved.map((p) => (
              <li key={p.rank} className={`border-l-2 pl-3 ${p.cited ? "border-l-accent-500" : "border-l-paper-300"}`}>
                <p className="tnum font-mono text-12 text-ink-500">
                  #{p.rank} {p.source_id ?? "not sent"} · {p.filename} · {pageLabel(p.page_number)} · score {formatScore(p.score)} ·{" "}
                  {p.above_threshold ? "above threshold" : "below threshold"}
                  {p.cited && <span className="text-accent-800"> · cited</span>}
                </p>
                <p className="reading mt-0.5 text-14 whitespace-pre-wrap text-ink-900">{p.excerpt}</p>
              </li>
            ))}
          </ol>
        )}
        <p className="mt-1 text-12 text-ink-500">Excerpts are truncated; the full text is in report.json.</p>
      </div>

      {c.judge && c.judge.status !== "not_applicable" && (
        <div>
          <h3 className="text-14 font-semibold text-ink-900">LLM judge — supplementary</h3>
          {c.judge.status === "scored" ? (
            <>
              <p className="tnum mt-1 font-mono text-12 text-ink-700">
                correctness {c.judge.correctness ?? "n/a"} · groundedness {c.judge.groundedness ?? "n/a"} · completeness{" "}
                {c.judge.completeness ?? "n/a"} · unsupported claims {yesNo(c.judge.unsupported_claims)} · citations support claims{" "}
                {yesNo(c.judge.citations_support_claims)}
              </p>
              {c.judge.rationale && <p className="mt-1 max-w-[80ch] text-13 text-ink-700">{c.judge.rationale}</p>}
            </>
          ) : (
            <p className="mt-1 text-13 text-ink-700">
              {c.judge.status === "error" ? "Judge error" : `Judge ${c.judge.status}`}
              {c.judge.error ? `: ${c.judge.error}` : "."}
            </p>
          )}
        </div>
      )}

      {c.notes && <p className="text-12 text-ink-500">Dataset note: {c.notes}</p>}
    </div>
  );
}
