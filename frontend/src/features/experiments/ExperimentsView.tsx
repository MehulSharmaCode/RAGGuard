/**
 * Experiments (UI_DESIGN_SPEC §8.4): MLflow evaluation runs read through the API, and a
 * side-by-side comparison of two runs with explicit comparability and trade-offs.
 */

import { ChevronDown, ChevronRight, Download, RotateCw } from "lucide-react";
import { Fragment, useMemo, useState } from "react";
import { routeHref } from "../../app/useRoute";
import { DownloadLink, Section } from "../../components/data/Section";
import { Button } from "../../components/ui/Button";
import { InlineAlert } from "../../components/ui/InlineAlert";
import { StatusTag, type Tone } from "../../components/ui/StatusTag";
import { compareRuns, getRun, listRuns, runArtifactUrl } from "../../lib/api/endpoints";
import { formatDateTime } from "../../lib/format";
import { ASSESSMENT_TEXT, formatDelta, formatMetric, groupBy, shortHash } from "../../lib/metrics";
import { useResource } from "../../lib/useResource";
import type { Assessment, MetricValue, RunComparison, RunList, RunSummary } from "../../types/api";

const UI_COMMAND = "backend/.venv/bin/mlflow ui --backend-store-uri sqlite:///mlflow.db --port 5050";
const RUN_COMMAND = "cd backend && .venv/bin/python -m app.evaluation.run_evaluation --skip-judge --label my-run";

const COLUMNS: [string, string][] = [
  ["correctness.case_pass_rate", "Case pass"],
  ["security.attack_success_rate", "Attack success"],
  ["answerability.false_answer_rate", "False answers"],
  ["latency.query.median_ms", "Median latency"],
];

const NOT_RECORDED = { value: "Not recorded", count: "", note: "This run does not record this metric.", missing: true };

function metric(run: RunSummary, key: string): MetricValue | undefined {
  return run.metrics.find((m) => m.key === key);
}

function runTitle(run: RunSummary): string {
  return run.label ?? run.run_name ?? run.run_id;
}

/** Newest run vs. the next older run on the same dataset and case count. */
function defaultPair(runs: RunSummary[]): [string, string] | null {
  const candidate = runs[0];
  if (!candidate || runs.length < 2) return null;
  const same = (r: RunSummary) =>
    r.params["dataset.fingerprint_sha256"] === candidate.params["dataset.fingerprint_sha256"] &&
    r.params["dataset.cases_run"] === candidate.params["dataset.cases_run"];
  const baseline = runs.slice(1).find(same) ?? runs[1]!;
  return [baseline.run_id, candidate.run_id];
}

function TrackingNotice({ data, onRetry }: { data: RunList; onRetry: () => void }) {
  const t = data.tracking;
  if (t.state === "available") {
    return (
      <p className="text-13 text-ink-700">
        <StatusTag tone="pass">Tracking store readable</StatusTag>{" "}
        <span className="tnum">
          {t.run_count} runs in experiment <span className="font-mono text-12">{t.experiment_name}</span> · {t.store}
        </span>
      </p>
    );
  }
  if (t.state === "dependency_missing") {
    return (
      <InlineAlert tone="warning" title="MLflow is not installed in the API environment">
        {t.detail} This does not mean there are no runs. Saved reports on the Evaluation page are unaffected. Install it with{" "}
        <span className="font-mono text-12">backend/.venv/bin/pip install -r backend/requirements-eval.txt</span> and restart the API.
      </InlineAlert>
    );
  }
  if (t.state === "unavailable") {
    return (
      <InlineAlert tone="error" title="The tracking store could not be read" action={<Button size="sm" icon={RotateCw} onClick={onRetry}>Retry</Button>}>
        {t.detail} Store: {t.store}. Question answering does not depend on it.
      </InlineAlert>
    );
  }
  return (
    <div className="max-w-[680px] space-y-2">
      <h2 className="text-18 font-semibold text-ink-900">No tracked runs yet</h2>
      <p className="text-14 text-ink-700">
        {t.detail} Store: {t.store}. Every evaluation run is logged to experiment{" "}
        <span className="font-mono text-12">{t.experiment_name}</span> unless it is started with <span className="font-mono text-12">--no-tracking</span>:
      </p>
      <pre className="relative overflow-x-auto rounded-sm bg-paper-200 px-3 py-2 font-mono text-12 text-ink-900">{RUN_COMMAND}</pre>
    </div>
  );
}

function RunDetailPanel({ run }: { run: RunSummary }) {
  const detail = useResource(run.run_id, (signal) => getRun(run.run_id, signal));
  const d = detail.data;
  return (
    <div className="space-y-3 text-13">
      <div className="flex flex-wrap items-center gap-2">
        {detail.loading && !d && <span className="text-ink-500">Loading run details…</span>}
        {detail.error && <span className="text-fail">Could not load run details: {detail.error.message}</span>}
        {d && d.artifacts.length === 0 && <span className="text-ink-500">This run has no report artifacts.</span>}
        {d?.artifacts.map((name) => (
          <DownloadLink key={name} href={runArtifactUrl(run.run_id, name)}>
            <Download aria-hidden="true" size={14} /> {name}
          </DownloadLink>
        ))}
        {run.local_report && run.ragguard_run_id && (
          <a href={routeHref("evaluation", run.ragguard_run_id)} className="text-accent-800 underline underline-offset-2 hover:text-ink-900">
            Open this report on the Evaluation page
          </a>
        )}
      </div>
      <dl className="grid gap-x-4 gap-y-0.5 sm:grid-cols-[auto_1fr]">
        <dt className="text-ink-500">MLflow run ID</dt>
        <dd className="font-mono text-12 break-all">{run.run_id}</dd>
        <dt className="text-ink-500">RAGGuard run ID</dt>
        <dd className="font-mono text-12">{run.ragguard_run_id ?? "—"}</dd>
        <dt className="text-ink-500">Git commit</dt>
        <dd className="font-mono text-12">
          {run.git_commit ?? "—"}
          {run.git_dirty === "true" && " (uncommitted changes)"}
        </dd>
        {run.imported && (
          <>
            <dt className="text-ink-500">Origin</dt>
            <dd>Imported later from a saved report (--import-report)</dd>
          </>
        )}
        {run.rescored_from && (
          <>
            <dt className="text-ink-500">Re-scored from</dt>
            <dd className="font-mono text-12">{run.rescored_from}</dd>
          </>
        )}
      </dl>
      <details>
        <summary className="cursor-pointer text-ink-900">Parameters ({Object.keys(run.params).length})</summary>
        <dl className="mt-1 grid gap-x-4 gap-y-0.5 font-mono text-12 sm:grid-cols-[auto_1fr]">
          {Object.entries(run.params)
            .sort()
            .map(([k, v]) => (
              <Fragment key={k}>
                <dt className="text-ink-500">{k}</dt>
                <dd className="break-all text-ink-900">{v}</dd>
              </Fragment>
            ))}
        </dl>
      </details>
      {d && (
        <details>
          <summary className="cursor-pointer text-ink-900">All logged metrics ({Object.keys(d.all_metrics).length})</summary>
          <dl className="tnum mt-1 grid max-h-80 gap-x-4 gap-y-0.5 overflow-y-auto font-mono text-12 sm:grid-cols-[auto_1fr]">
            {Object.entries(d.all_metrics).map(([k, v]) => (
              <Fragment key={k}>
                <dt className="text-ink-500">{k}</dt>
                <dd className="text-ink-900">{v}</dd>
              </Fragment>
            ))}
          </dl>
        </details>
      )}
    </div>
  );
}

function RunsTable({
  runs,
  pair,
  onPair,
}: {
  runs: RunSummary[];
  pair: [string, string] | null;
  onPair: (pair: [string, string]) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const [baseline, candidate] = pair ?? [null, null];
  return (
    <div className="relative overflow-x-auto border-y border-paper-300">
      <table className="w-full min-w-[920px] border-collapse text-13" aria-label="Tracked evaluation runs">
        <thead className="text-left text-12 text-ink-500">
          <tr className="border-b border-paper-300">
            <th scope="col" className="py-2 pl-1 font-medium">Baseline</th>
            <th scope="col" className="py-2 pr-2 font-medium">Candidate</th>
            <th scope="col" className="py-2 pr-2 font-medium">Run</th>
            <th scope="col" className="py-2 pr-2 font-medium">Started</th>
            <th scope="col" className="py-2 pr-2 font-medium">Dataset</th>
            <th scope="col" className="py-2 pr-2 font-medium">Configuration</th>
            {COLUMNS.map(([key, label]) => (
              <th key={key} scope="col" className="py-2 pr-2 text-right font-medium">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => {
            const p = run.params;
            const expanded = open === run.run_id;
            return (
              <Fragment key={run.run_id}>
                <tr className="border-b border-paper-300 align-top hover:bg-paper-200">
                  <td className="py-2 pl-2">
                    <input
                      type="radio"
                      name="baseline"
                      aria-label={`Use ${runTitle(run)} as baseline`}
                      checked={baseline === run.run_id}
                      onChange={() => onPair([run.run_id, candidate ?? run.run_id])}
                    />
                  </td>
                  <td className="py-2 pr-2 pl-3">
                    <input
                      type="radio"
                      name="candidate"
                      aria-label={`Use ${runTitle(run)} as candidate`}
                      checked={candidate === run.run_id}
                      onChange={() => onPair([baseline ?? run.run_id, run.run_id])}
                    />
                  </td>
                  <td className="py-2 pr-2">
                    <button
                      type="button"
                      aria-expanded={expanded}
                      onClick={() => setOpen(expanded ? null : run.run_id)}
                      className="inline-flex items-start gap-1 rounded-xs text-left text-ink-900 hover:underline"
                    >
                      {expanded ? <ChevronDown aria-hidden="true" size={14} className="mt-0.5 shrink-0" /> : <ChevronRight aria-hidden="true" size={14} className="mt-0.5 shrink-0" />}
                      <span>
                        <span className="font-medium">{runTitle(run)}</span>
                        <span className="sr-only">: {expanded ? "hide" : "show"} details</span>
                      </span>
                    </button>
                    <span className="block pl-5 font-mono text-12 text-ink-500">
                      {run.run_name} · {run.status.toLowerCase()}
                      {run.imported && " · imported"}
                      {run.rescored_from && " · re-scored"}
                    </span>
                  </td>
                  <td className="py-2 pr-2 text-12 whitespace-nowrap text-ink-700">{run.start_time ? formatDateTime(run.start_time) : "—"}</td>
                  <td className="py-2 pr-2 text-12 text-ink-700">
                    <span className="block">{p["dataset.dataset_id"] ?? "unknown dataset"}</span>
                    v{p["dataset.version"] ?? "?"} · {p["dataset.cases_run"] ?? "?"} cases
                    <span className="block font-mono text-ink-500">{shortHash(p["dataset.fingerprint_sha256"], 8)}</span>
                  </td>
                  <td className="py-2 pr-2 text-12 text-ink-700">
                    <span className="font-mono">{p["config.generation_model"] ?? "?"}</span> ({p["config.generation_provider"] ?? "?"})
                    <span className="block">
                      prompt {p["config.prompt_version"] ?? "?"} · threshold {p["config.min_retrieval_score"] ?? "?"} · top-k {p["config.top_k"] ?? "?"}
                    </span>
                  </td>
                  {COLUMNS.map(([key]) => {
                    const m = metric(run, key);
                    const text = m ? formatMetric(m) : NOT_RECORDED;
                    return (
                      <td key={key} className={`tnum py-2 pr-2 text-right font-mono text-12 ${text.missing ? "text-ink-500" : "text-ink-900"}`} title={text.note ?? undefined}>
                        {text.value}
                        {text.count && <span className="block text-ink-500">{text.count}</span>}
                      </td>
                    );
                  })}
                </tr>
                {expanded && (
                  <tr className="border-b border-paper-300 bg-paper-50">
                    <td colSpan={6 + COLUMNS.length} className="px-3 py-3">
                      <RunDetailPanel run={run} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const ASSESSMENT_TONE: Record<Assessment, Tone> = {
  improved: "pass",
  regressed: "fail",
  unchanged: "pending",
  changed: "pending",
  not_comparable: "warn",
  unavailable: "pending",
};

function ComparisonView({ comparison }: { comparison: RunComparison }) {
  const { baseline, candidate, improved, regressed } = comparison;
  const changed = comparison.params.filter((p) => p.changed);
  return (
    <div className="space-y-4">
      <p className="text-13 text-ink-700">
        Baseline <span className="font-medium text-ink-900">{runTitle(baseline)}</span> → candidate{" "}
        <span className="font-medium text-ink-900">{runTitle(candidate)}</span>
      </p>
      {comparison.comparable ? (
        <StatusTag tone="pass">Comparable: same dataset fingerprint, case count, and report schema</StatusTag>
      ) : (
        <InlineAlert tone="warning" title="Not directly comparable">
          The runs used different datasets or case counts, so no metric is marked as improved or regressed.
        </InlineAlert>
      )}
      {improved.length > 0 && regressed.length > 0 && (
        <InlineAlert tone="warning" title="Trade-off, not an unqualified improvement">
          The candidate improves {improved.length} metric(s) but regresses {regressed.length}: {regressed.join(", ")}.
        </InlineAlert>
      )}
      {improved.length > 0 && regressed.length === 0 && (
        <InlineAlert tone="info" title={`No regression among the compared metrics`}>
          The candidate improves {improved.length} metric(s); metrics that are unavailable or not comparable are not counted.
        </InlineAlert>
      )}
      {improved.length === 0 && regressed.length > 0 && (
        <InlineAlert tone="error" title="Regression">
          The candidate regresses {regressed.join(", ")} and improves nothing that was compared.
        </InlineAlert>
      )}
      <ul className="list-disc space-y-0.5 pl-5 text-12 text-ink-500">
        {comparison.notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>

      <div>
        <h3 className="section-label mb-1">Parameters ({changed.length} changed)</h3>
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[560px] border-collapse text-13">
            <thead className="text-left text-12 text-ink-500">
              <tr className="border-b border-paper-300">
                <th scope="col" className="py-1.5 pr-3 font-medium">Parameter</th>
                <th scope="col" className="py-1.5 pr-3 font-medium">Baseline</th>
                <th scope="col" className="py-1.5 pr-3 font-medium">Candidate</th>
                <th scope="col" className="py-1.5 font-medium"><span className="sr-only">Changed</span></th>
              </tr>
            </thead>
            <tbody>
              {comparison.params.map((p) => (
                <tr key={p.key} className={`border-b border-paper-300 last:border-b-0 ${p.changed ? "font-medium text-ink-900" : "text-ink-700"}`}>
                  <th scope="row" className="py-1.5 pr-3 text-left font-normal">{p.label}</th>
                  <td className="py-1.5 pr-3 font-mono text-12 break-all">{p.baseline ?? "not recorded"}</td>
                  <td className="py-1.5 pr-3 font-mono text-12 break-all">{p.candidate ?? "not recorded"}</td>
                  <td className="py-1.5 text-12">{p.changed ? "Changed" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="space-y-4">
        {groupBy(comparison.metrics, (m) => m.group).map(([group, rows]) => (
          <div key={group}>
            <h3 className="section-label mb-1">{group}</h3>
            <div className="relative overflow-x-auto">
              <table className="tnum w-full min-w-[640px] border-collapse text-13">
                <thead className="text-left text-12 text-ink-500">
                  <tr className="border-b border-paper-300">
                    <th scope="col" className="py-1.5 pr-3 font-medium">Metric</th>
                    <th scope="col" className="py-1.5 pr-3 text-right font-medium">Baseline</th>
                    <th scope="col" className="py-1.5 pr-3 text-right font-medium">Candidate</th>
                    <th scope="col" className="py-1.5 pr-3 text-right font-medium">Change</th>
                    <th scope="col" className="py-1.5 font-medium">Assessment</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((d) => {
                    const b = formatMetric(d.baseline);
                    const c = formatMetric(d.candidate);
                    return (
                      <tr key={d.key} className="border-b border-paper-300 last:border-b-0">
                        <th scope="row" className="py-1.5 pr-3 text-left font-normal text-ink-900">{d.label}</th>
                        <td className={`py-1.5 pr-3 text-right font-mono ${b.missing ? "text-ink-500" : ""}`} title={b.note ?? undefined}>
                          {b.value} <span className="text-12 text-ink-500">{b.count}</span>
                        </td>
                        <td className={`py-1.5 pr-3 text-right font-mono ${c.missing ? "text-ink-500" : ""}`} title={c.note ?? undefined}>
                          {c.value} <span className="text-12 text-ink-500">{c.count}</span>
                        </td>
                        <td className="py-1.5 pr-3 text-right font-mono text-12">{formatDelta(d.candidate, d.delta)}</td>
                        <td className="py-1.5">
                          <StatusTag tone={ASSESSMENT_TONE[d.assessment]}>{ASSESSMENT_TEXT[d.assessment]}</StatusTag>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ExperimentsView() {
  const runs = useResource("runs", listRuns);
  const list = useMemo(() => runs.data?.runs ?? [], [runs.data]);
  const [chosen, setChosen] = useState<[string, string] | null>(null);
  const valid = chosen && chosen.every((id) => list.some((r) => r.run_id === id)) ? chosen : null;
  const pair = valid ?? defaultPair(list);
  const pairKey = pair ? `${pair[0]}:${pair[1]}` : null;
  const comparison = useResource(pairKey, (signal) => compareRuns(pair![0], pair![1], signal));

  return (
    <div className="mx-auto max-w-[1280px] space-y-6 px-4 py-6 md:px-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="max-w-[75ch] text-14 text-ink-700">
          Evaluation runs tracked in MLflow: configuration, metrics, and report artifacts per run. Pick a baseline and a candidate to
          compare them. Read-only: nothing is created, changed, or deleted from here.
        </p>
        <Button size="sm" icon={RotateCw} loading={runs.loading} onClick={runs.refresh}>
          Reload
        </Button>
      </div>

      {runs.error && (
        <InlineAlert tone="error" title="Could not load tracked runs" action={<Button size="sm" icon={RotateCw} onClick={runs.refresh}>Retry</Button>}>
          {runs.error.message}
        </InlineAlert>
      )}
      {runs.loading && !runs.data && (
        <p className="text-13 text-ink-500" aria-busy="true">
          Reading the tracking store…
        </p>
      )}
      {runs.data && <TrackingNotice data={runs.data} onRetry={runs.refresh} />}

      {list.length > 0 && (
        <>
          <Section
            id="runs-title"
            title="Runs"
            description={
              <>
                Newest first. Expand a run for its parameters and downloadable reports. These are evaluation runs, not GenAI traces:
                MLflow&apos;s Traces tab is expected to be empty. To browse the same store in MLflow&apos;s own UI, run{" "}
                <span className="font-mono text-12">{UI_COMMAND}</span> from the repository root.
              </>
            }
          >
            <RunsTable runs={list} pair={pair} onPair={setChosen} />
          </Section>
          <Section id="compare-title" title="Comparison">
            {!pair && <p className="text-13 text-ink-700">At least two runs are needed for a comparison.</p>}
            {comparison.error && (
              <InlineAlert tone="error" title="Could not compare these runs">
                {comparison.error.message}
              </InlineAlert>
            )}
            {comparison.loading && !comparison.data && (
              <p className="text-13 text-ink-500" aria-busy="true">
                Comparing…
              </p>
            )}
            {comparison.data && <ComparisonView comparison={comparison.data} />}
          </Section>
        </>
      )}
    </div>
  );
}
