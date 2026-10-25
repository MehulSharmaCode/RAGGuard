/**
 * Evaluation dashboard (UI_DESIGN_SPEC §8.3): saved reports from evaluation/results,
 * read through the API. Opening the view never starts an evaluation.
 */

import { Download, RotateCw } from "lucide-react";
import { useState } from "react";
import { MetricLedger } from "../../components/data/MetricLedger";
import { DownloadLink, fieldClass, Section } from "../../components/data/Section";
import { Button } from "../../components/ui/Button";
import { InlineAlert } from "../../components/ui/InlineAlert";
import { StatusTag } from "../../components/ui/StatusTag";
import { routeHref } from "../../app/useRoute";
import { evaluationFileUrl, getEvaluation, listEvaluations } from "../../lib/api/endpoints";
import { formatDateTime, formatMs, plural } from "../../lib/format";
import { formatMetric, shortHash } from "../../lib/metrics";
import { useResource } from "../../lib/useResource";
import type { EvaluationDetail, EvaluationSummary, FindingKind, LatencySummary, MetricValue } from "../../types/api";
import { CaseTable, type CaseFilters, type VerdictFilter } from "./CaseTable";
import { FINDING_LABELS } from "./labels";

export const RUN_COMMAND = "cd backend && .venv/bin/python -m app.evaluation.run_evaluation --skip-judge";

export function runStatusTag(status: string | null) {
  if (status === "completed") return <StatusTag tone="pass">Run completed</StatusTag>;
  if (status === "partial") return <StatusTag tone="warn">Run partial</StatusTag>;
  if (status === "failed") return <StatusTag tone="fail">Run failed</StatusTag>;
  return <StatusTag tone="pending">Status not recorded</StatusTag>;
}

function optionText(r: EvaluationSummary): string {
  if (!r.readable) return `${r.run_id} · unreadable`;
  const parts = [r.run_id, `${r.dataset_id ?? "unknown dataset"} v${r.dataset_version ?? "?"}`, `${r.cases_run ?? "?"} cases`, r.status ?? "unknown status"];
  if (r.params["config.prompt_version"]) parts.push(`prompt ${r.params["config.prompt_version"]}`);
  if (r.rescored_from) parts.push("re-scored");
  return parts.join(" · ");
}

function headline(m: MetricValue | undefined, noun: string, verb: string): string | null {
  if (!m || !m.available || m.value === null || m.numerator === null || m.denominator === null) return null;
  return `${m.numerator} of ${plural(m.denominator, noun)} ${verb} (${formatMetric(m).value})`;
}

function RunHeader({ detail }: { detail: EvaluationDetail }) {
  const s = detail.summary;
  const p = s.params;
  const metric = (key: string) => detail.metrics.find((m) => m.key === key);
  const lines = [
    headline(metric("correctness.case_pass_rate"), "case", "passed"),
    headline(metric("security.attack_success_rate"), "attack case", "succeeded"),
  ].filter(Boolean);
  const judge =
    p["config.judge_enabled"] === "true"
      ? `judge ${p["config.judge_model"]} (${p["config.judge_prompt_version"]})${p["config.judge_same_model_as_generation"] === "true" ? ", same model as generation" : ""}`
      : "judge disabled";
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <p className="section-label">Report</p>
          <p className="font-mono text-14 break-all text-ink-900">{s.run_id}</p>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-13 text-ink-700">
            {runStatusTag(s.status)}
            {s.started_at && <span>started {formatDateTime(s.started_at)}</span>}
            {s.finished_at && <span>finished {formatDateTime(s.finished_at)}</span>}
          </div>
          {s.status_detail && <p className="text-12 text-ink-500">{s.status_detail} (execution status, not a quality verdict)</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <DownloadLink href={evaluationFileUrl(s.run_id, "report.json")}>
            <Download aria-hidden="true" size={14} /> report.json
          </DownloadLink>
          <DownloadLink href={evaluationFileUrl(s.run_id, "report.md")}>
            <Download aria-hidden="true" size={14} /> report.md
          </DownloadLink>
        </div>
      </div>
      <dl className="grid gap-x-4 gap-y-1 text-13 sm:grid-cols-[auto_1fr]">
        <dt className="text-ink-500">Dataset</dt>
        <dd className="text-ink-900">
          {s.dataset_id} v{s.dataset_version} · {s.cases_run} of {s.cases_in_dataset} cases ·{" "}
          <span className="font-mono text-12" title={s.dataset_fingerprint ?? undefined}>
            sha256 {shortHash(s.dataset_fingerprint)}
          </span>
        </dd>
        <dt className="text-ink-500">Configuration</dt>
        <dd className="text-ink-900">
          {p["config.generation_provider"]} <span className="font-mono text-12">{p["config.generation_model"]}</span> · prompt{" "}
          {p["config.prompt_version"]} · threshold {p["config.min_retrieval_score"]} · top-k {p["config.top_k"]} · chunks{" "}
          {p["config.chunk_size_tokens"]}/{p["config.chunk_overlap_tokens"]} tokens · <span className="font-mono text-12">{p["config.embedding_model"]}</span> ·{" "}
          {judge}
        </dd>
        {s.rescored_from && (
          <>
            <dt className="text-ink-500">Re-scored</dt>
            <dd className="text-ink-900">
              Recorded answers of <span className="font-mono text-12">{s.rescored_from}</span> scored again with the current evaluator (no new
              model calls).
            </dd>
          </>
        )}
      </dl>
      {lines.length > 0 ? (
        <p className="tnum text-22 font-semibold text-ink-900">{lines.join(" · ")}</p>
      ) : (
        <InlineAlert tone="info" title={`Report schema ${s.schema_version ?? "unknown"}: no case verdicts or security metrics`}>
          This report predates the Stage 5 evaluator, so pass rates and attack metrics are shown as “Not recorded”, not as zero.
          Its dataset is not comparable with later runs.
        </InlineAlert>
      )}
      {detail.fatal_error && (
        <InlineAlert tone="error" title="The run failed">
          {detail.fatal_error}
        </InlineAlert>
      )}
    </div>
  );
}

const OPEN_ISSUES: { kind: FindingKind; noun: string }[] = [
  { kind: "attack_succeeded", noun: "successful prompt-injection attack" },
  { kind: "canary_leak", noun: "canary leak" },
  { kind: "superseded_citation", noun: "superseded-source citation" },
  { kind: "false_answer", noun: "false answer" },
  { kind: "false_refusal", noun: "false refusal" },
];

function OpenIssues({ detail, onShow }: { detail: EvaluationDetail; onShow: (kind: FindingKind) => void }) {
  const counts = OPEN_ISSUES.map((i) => ({
    ...i,
    n: detail.cases.filter((c) => c.findings.some((f) => f.kind === i.kind)).length,
  })).filter((i) => i.n > 0);
  if (counts.length === 0) return null;
  return (
    <InlineAlert tone="warning" title="Open findings in this run">
      <p>
        {counts.map((i) => plural(i.n, i.noun)).join(", ")}. These are why the evaluation exists: synthetic cases that pass do not
        prove resistance to other attacks.
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        {counts.map((i) => (
          <Button key={i.kind} size="sm" onClick={() => onShow(i.kind)}>
            Show {FINDING_LABELS[i.kind].toLowerCase()} cases
          </Button>
        ))}
      </div>
    </InlineAlert>
  );
}

const LATENCY_ROWS: [string, string][] = [
  ["query", "All queries"],
  ["query_with_generation", "Model called"],
  ["query_without_generation", "Fallback before the model"],
];

function LatencyTable({ latency }: { latency: Record<string, LatencySummary> }) {
  const rows = LATENCY_ROWS.filter(([key]) => latency[key]);
  if (rows.length === 0) return <p className="text-13 text-ink-500">Latency was not recorded in this report.</p>;
  const ms = (v: number | null) => (v === null ? "n/a" : formatMs(v));
  return (
    <div className="relative overflow-x-auto">
      <table className="tnum w-full min-w-[480px] border-collapse text-13">
        <thead className="text-left text-12 text-ink-500">
          <tr className="border-b border-paper-300">
            <th scope="col" className="py-1.5 pr-3 font-medium">Queries</th>
            <th scope="col" className="py-1.5 pr-3 text-right font-medium">Count</th>
            <th scope="col" className="py-1.5 pr-3 text-right font-medium">Median</th>
            <th scope="col" className="py-1.5 pr-3 text-right font-medium">p95</th>
            <th scope="col" className="py-1.5 text-right font-medium">Max</th>
          </tr>
        </thead>
        <tbody className="font-mono">
          {rows.map(([key, label]) => {
            const l = latency[key]!;
            return (
              <tr key={key} className="border-b border-paper-300 last:border-b-0">
                <th scope="row" className="py-1.5 pr-3 text-left font-sans font-normal">{label}</th>
                <td className="py-1.5 pr-3 text-right">{l.count}</td>
                <td className="py-1.5 pr-3 text-right">{ms(l.median_ms)}</td>
                <td className="py-1.5 pr-3 text-right">{ms(l.p95_ms)}</td>
                <td className="py-1.5 text-right">{ms(l.max_ms)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="mt-1 text-12 text-ink-500">Wall-clock time per query on the machine that ran the evaluation; p95 equals the maximum for fewer than 20 queries.</p>
    </div>
  );
}

function JudgeSection({ detail }: { detail: EvaluationDetail }) {
  const j = detail.judge;
  if (!j) return <p className="text-13 text-ink-500">This report has no judge section.</p>;
  if (!j.enabled) return <p className="text-13 text-ink-700">The LLM judge was disabled for this run (--skip-judge); judge metrics are n/a.</p>;
  return (
    <div className="space-y-1 text-13 text-ink-700">
      <p>
        Judge <span className="font-mono text-12">{j.model}</span> scored {j.scored ?? "?"} of {j.eligible_cases ?? "?"} eligible answers;{" "}
        {plural(j.errors.length, "judge error")}.
        {j.same_model_as_generation && " The judge is the same model that generated the answers, so its scores may be biased."}
      </p>
      {j.errors.length > 0 && <p>Judge errors: {j.errors.join(", ")}</p>}
      <p className="text-12 text-ink-500">Judge scores are supplementary and never decide a case verdict.</p>
    </div>
  );
}

function defaultFilters(detail: EvaluationDetail): CaseFilters {
  const has = (v: string) => detail.cases.some((c) => c.verdict === v);
  const verdict: VerdictFilter = has("fail") ? "fail" : has("unscored") ? "findings" : "all";
  return { verdict, category: "all", finding: "any", search: "" };
}

function ReportBody({ detail }: { detail: EvaluationDetail }) {
  const [filters, setFilters] = useState<CaseFilters>(() => defaultFilters(detail));
  const sameModel = detail.judge?.same_model_as_generation
    ? "Scored by the same model that generated the answers; supplementary only."
    : "Supplementary only; never a verdict.";
  return (
    <div className="space-y-6">
      <RunHeader detail={detail} />
      <OpenIssues
        detail={detail}
        onShow={(kind) => {
          setFilters({ verdict: "all", category: "all", finding: kind, search: "" });
          document.getElementById("cases-title")?.scrollIntoView?.({ block: "start" });
        }}
      />
      <Section
        id="metrics-title"
        title="Metrics"
        description="Deterministic checks from the report, each with its denominator. “Not recorded” means the report does not contain the metric; “n/a” means no case applied."
      >
        <MetricLedger metrics={detail.metrics} judgeNote={sameModel} />
      </Section>
      <Section id="cases-title" title="Cases" description="Expected versus actual behaviour for each case, with the findings that made it fail.">
        {detail.cases.length === 0 ? (
          <p className="text-13 text-ink-700">This report contains no case records.</p>
        ) : (
          <CaseTable cases={detail.cases} filters={filters} onFilters={setFilters} />
        )}
      </Section>
      <Section id="latency-title" title="Latency">
        <LatencyTable latency={detail.latency} />
      </Section>
      <Section id="judge-title" title="LLM judge">
        <JudgeSection detail={detail} />
      </Section>
      <Section id="about-title" title="Definitions and limitations">
        <details className="text-13">
          <summary className="cursor-pointer text-ink-900">Metric definitions ({detail.metric_definitions.length})</summary>
          <dl className="mt-2 space-y-2">
            {detail.metric_definitions.map((d) => (
              <div key={d.name}>
                <dt className="font-mono text-12 text-ink-900">{d.name}</dt>
                <dd className="text-ink-700">{d.definition}</dd>
                <dd className="text-12 text-ink-500">Denominator: {d.denominator}</dd>
              </div>
            ))}
          </dl>
        </details>
        <details className="mt-2 text-13">
          <summary className="cursor-pointer text-ink-900">Limitations recorded in the report ({detail.limitations.length})</summary>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-ink-700">
            {detail.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
        </details>
      </Section>
    </div>
  );
}

export function EmptyEvaluations({ resultsDir }: { resultsDir: string }) {
  return (
    <div className="max-w-[640px] space-y-2">
      <h2 className="text-18 font-semibold text-ink-900">No evaluation reports yet</h2>
      <p className="text-14 text-ink-700">
        Reports appear here after the evaluation runner writes them to <span className="font-mono text-13">{resultsDir}</span>. Opening this
        page never starts a run. To create one, run (with Ollama running):
      </p>
      <pre className="relative overflow-x-auto rounded-sm bg-paper-200 px-3 py-2 font-mono text-12 text-ink-900">{RUN_COMMAND}</pre>
    </div>
  );
}

export default function EvaluationView({ runId }: { runId: string | null }) {
  const list = useResource("evaluations", listEvaluations);
  const reports = list.data?.reports ?? [];
  const latest = reports.find((r) => r.readable) ?? null;
  const selectedId = runId ?? latest?.run_id ?? null;
  const detail = useResource(selectedId, (signal) => getEvaluation(selectedId!, signal));
  const choose = (id: string) => {
    window.location.hash = routeHref("evaluation", id);
  };

  return (
    <div className="mx-auto max-w-[1200px] space-y-6 px-4 py-6 md:px-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="max-w-[70ch]">
          <p className="text-14 text-ink-700">
            Saved results of the offline evaluation suite: answer correctness, abstention, citations, prompt-injection attacks, and
            latency on fixed benchmark datasets (each report names its dataset). Read-only; runs are started from the CLI.
          </p>
        </div>
        <div className="flex min-w-0 flex-wrap items-end gap-2">
          {reports.length > 0 && (
            <label className="flex min-w-0 flex-col gap-1 text-12 text-ink-500">
              Report ({reports.length} saved, newest first)
              <select name="report" className={`${fieldClass} w-full max-w-[520px]`} value={selectedId ?? ""} onChange={(e) => choose(e.target.value)}>
                {runId && !reports.some((r) => r.run_id === runId) && <option value={runId}>{runId} (not found)</option>}
                {reports.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {optionText(r)}
                  </option>
                ))}
              </select>
            </label>
          )}
          <Button size="sm" icon={RotateCw} loading={list.loading || detail.loading} onClick={() => { list.refresh(); detail.refresh(); }}>
            Reload
          </Button>
        </div>
      </div>

      {list.error && (
        <InlineAlert tone="error" title="Could not load evaluation reports" action={<Button size="sm" icon={RotateCw} onClick={list.refresh}>Retry</Button>}>
          {list.error.message}
        </InlineAlert>
      )}
      {list.loading && !list.data && (
        <p className="text-13 text-ink-500" aria-busy="true">
          Loading evaluation reports…
        </p>
      )}
      {list.data && reports.length === 0 && <EmptyEvaluations resultsDir={list.data.results_dir} />}
      {list.data && reports.length > 0 && !latest && !runId && (
        <InlineAlert tone="warning" title="No readable report">
          {reports.length} report folder(s) exist, but none could be read: {reports[0]?.problem}
        </InlineAlert>
      )}

      {detail.error && (
        <InlineAlert
          tone="error"
          title={detail.error.code === "report_not_found" ? "Report not found" : "Could not load this report"}
          action={
            latest && latest.run_id !== selectedId ? (
              <Button size="sm" onClick={() => choose(latest.run_id)}>
                Open the latest report
              </Button>
            ) : undefined
          }
        >
          {detail.error.message}
          {detail.error.code && <span className="ml-1 font-mono text-12">({detail.error.code})</span>}
        </InlineAlert>
      )}
      {detail.loading && !detail.data && selectedId && (
        <p className="text-13 text-ink-500" aria-busy="true">
          Loading report {selectedId}…
        </p>
      )}
      {detail.data && <ReportBody key={detail.data.summary.run_id} detail={detail.data} />}
    </div>
  );
}
