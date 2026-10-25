/**
 * Pipeline (UI_DESIGN_SPEC §8.5, Stage 5.5 scope): the RAG flow as implemented, live
 * component status from GET /system/status, recent GitHub Actions runs (Stage 7, read from
 * GitHub's public API; see lib/api/github.ts), and the stages that do not exist yet.
 * Only runs GitHub reports are shown: nothing is inferred, and nothing is deployed by CI.
 */

import { ArrowDown, ArrowRight, ExternalLink, RotateCw } from "lucide-react";
import { Fragment, useRef } from "react";
import { routeHref } from "../../app/useRoute";
import { Section } from "../../components/data/Section";
import { Button } from "../../components/ui/Button";
import { InlineAlert } from "../../components/ui/InlineAlert";
import { StatusTag, type Tone } from "../../components/ui/StatusTag";
import { getSystemStatus } from "../../lib/api/endpoints";
import {
  actionsUrl,
  commitUrl,
  configuredRepository,
  getCiRuns,
  type CiRun,
  type CiRuns,
  type RunState,
} from "../../lib/api/github";
import { formatDateTime } from "../../lib/format";
import { formatMetric } from "../../lib/metrics";
import { useResource } from "../../lib/useResource";
import type { ComponentState, SystemStatus } from "../../types/api";

type Config = SystemStatus["configuration"];

interface Step {
  title: string;
  detail: string;
}

const value = (config: Config | null, key: string): string => {
  const v = config?.[key];
  return v === null || v === undefined ? "unknown" : String(v);
};

function ingestSteps(c: Config | null): Step[] {
  return [
    {
      title: "Upload and validation",
      detail: `POST /ingest. PDF or UTF-8 TXT up to ${value(c, "max_upload_size_mb")} MB; type, size, and content are checked first.`,
    },
    {
      title: "Text extraction and chunking",
      detail: `Text per PDF page (pypdf, layout-aware: page regions and table rows are rebuilt from text positions). Chunks pack whole regions up to ${value(c, "chunk_size_tokens")} tokens; longer regions are split with ${value(c, "chunk_overlap_tokens")}-token overlap (embedding model's tokenizer).`,
    },
    {
      title: "Embedding",
      detail: `${value(c, "embedding_model")}, run locally: each chunk and its sub-units (rows, list items, sentences); questions use the same model.`,
    },
    {
      title: "Vector storage",
      detail: `Qdrant (${value(c, "qdrant_mode")}), collection ${value(c, "qdrant_collection")}, with document, page, and chunk metadata.`,
    },
  ];
}

function querySteps(c: Config | null): Step[] {
  return [
    {
      title: "Retrieval and evidence scoring",
      detail: `POST /query. Semantic and lexical (BM25) candidates are fused (hybrid index; older indexes: semantic only); up to ${value(c, "default_top_k")} chunks, each scored by its best-matching sub-unit (cosine), are evidence only if they score at least ${value(c, "min_retrieval_score")}, ordered by that score. Each passage is the whole chunk, extended by the adjacent windows of the same region on its page (structure-aware indexes). A document that another retrieved passage explicitly replaces is left out unless the question asks about history or change. Without evidence the safe fallback is returned and the model is not called.`,
    },
    {
      title: "Prompt construction and generation",
      detail: `Prompt ${value(c, "prompt_version")}: passages are quoted as untrusted data (markup neutralised, instruction-like text addressed to an assistant withheld, instruction and supersession labels, priority rules), answered by ${value(c, "generation_provider")} ${value(c, "generation_model")}.`,
    },
    {
      title: "Citations and fallback",
      detail:
        "[Sn] citations are matched to the evidence passages. An answer must cite at least one passage, only existing passages, and only values and pages found in the evidence; otherwise it is regenerated once and then withheld. A decline, a reply that repeats the system prompt, or a withheld answer becomes the safe fallback (no_results, below_threshold, model_declined).",
    },
  ];
}

function Flow({ label, steps, start }: { label: string; steps: Step[]; start: number }) {
  return (
    <div>
      <h3 className="section-label mb-2">{label}</h3>
      <ol className="flex flex-col gap-1 lg:flex-row lg:items-stretch">
        {steps.map((step, i) => (
          <Fragment key={step.title}>
            <li className="flex-1 rounded-sm border border-paper-300 bg-paper-50 px-3 py-2">
              <p className="text-14 font-medium text-ink-900">
                <span className="tnum mr-1.5 font-mono text-12 text-ink-500">{start + i}</span>
                {step.title}
              </p>
              <p className="mt-1 text-12 text-ink-700">{step.detail}</p>
            </li>
            {i < steps.length - 1 && (
              <li aria-hidden="true" className="flex items-center justify-center text-ink-500">
                <ArrowDown size={16} className="lg:hidden" />
                <ArrowRight size={16} className="hidden lg:block" />
              </li>
            )}
          </Fragment>
        ))}
      </ol>
    </div>
  );
}

const STATE: Record<ComponentState, { tone: Tone; label: string }> = {
  healthy: { tone: "pass", label: "Healthy" },
  configured: { tone: "pending", label: "Configured, not verified" },
  unavailable: { tone: "fail", label: "Unavailable" },
  not_implemented: { tone: "pending", label: "Not implemented" },
};

function StatusTable({ status }: { status: SystemStatus }) {
  const live = status.components.filter((c) => c.state !== "not_implemented");
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[640px] border-collapse text-13" aria-label="Component status">
        <thead className="text-left text-12 text-ink-500">
          <tr className="border-b border-paper-300">
            <th scope="col" className="py-1.5 pr-3 font-medium">Component</th>
            <th scope="col" className="py-1.5 pr-3 font-medium">Status</th>
            <th scope="col" className="py-1.5 pr-3 font-medium">Detail</th>
            <th scope="col" className="py-1.5 font-medium">Check</th>
          </tr>
        </thead>
        <tbody>
          {live.map((c) => (
            <tr key={c.id} className="border-b border-paper-300 align-top last:border-b-0">
              <th scope="row" className="py-2 pr-3 text-left font-normal whitespace-nowrap text-ink-900">{c.label}</th>
              <td className="py-2 pr-3 whitespace-nowrap">
                <StatusTag tone={STATE[c.state].tone}>{STATE[c.state].label}</StatusTag>
              </td>
              <td className="py-2 pr-3 text-ink-700">{c.detail}</td>
              <td className="py-2 text-12 whitespace-nowrap text-ink-500">{c.verified ? "Live check" : "Not checked"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const RUN: Record<RunState, { tone: Tone; label: string }> = {
  success: { tone: "pass", label: "Passed" },
  failure: { tone: "fail", label: "Failed" },
  cancelled: { tone: "warn", label: "Cancelled" },
  in_progress: { tone: "loading", label: "Running" },
  queued: { tone: "pending", label: "Queued" },
  action_required: { tone: "warn", label: "Needs approval" },
  other: { tone: "pending", label: "Not completed" },
};

function runLabel(run: CiRun): string {
  const base = RUN[run.state].label;
  // Show GitHub's own words for outcomes this view has no specific label for (skipped, neutral, ...).
  return run.state === "other" ? (run.conclusion ?? run.status).replaceAll("_", " ") : base;
}

function RunsTable({ ci }: { ci: CiRuns }) {
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[720px] border-collapse text-13" aria-label="Recent workflow runs">
        <thead className="text-left text-12 text-ink-500">
          <tr className="border-b border-paper-300">
            <th scope="col" className="py-1.5 pr-3 font-medium">Run</th>
            <th scope="col" className="py-1.5 pr-3 font-medium">Result</th>
            <th scope="col" className="py-1.5 pr-3 font-medium">Trigger</th>
            <th scope="col" className="py-1.5 pr-3 font-medium">Commit</th>
            <th scope="col" className="py-1.5 font-medium">Started</th>
          </tr>
        </thead>
        <tbody>
          {ci.runs.map((run) => (
            <tr key={run.id} className="border-b border-paper-300 align-top last:border-b-0">
              <th scope="row" className="py-2 pr-3 text-left font-normal text-ink-900">
                <a
                  href={run.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-flex items-center gap-1 text-accent-800 underline underline-offset-2"
                  aria-label={`Open run ${run.runNumber} of ${run.workflowName} on GitHub`}
                >
                  {run.workflowName} #{run.runNumber}
                  <ExternalLink aria-hidden="true" size={12} />
                </a>
                <span className="block text-12 text-ink-500">
                  {run.title}
                  {run.attempt > 1 && ` · attempt ${run.attempt}`}
                </span>
              </th>
              <td className="py-2 pr-3 whitespace-nowrap">
                <StatusTag tone={RUN[run.state].tone}>{runLabel(run)}</StatusTag>
              </td>
              <td className="py-2 pr-3 text-ink-700">
                {run.event.replaceAll("_", " ")}
                {run.branch && <span className="block font-mono text-12 text-ink-500">{run.branch}</span>}
              </td>
              <td className="py-2 pr-3 whitespace-nowrap">
                <a
                  href={commitUrl(ci.repository, run.commit)}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="font-mono text-12 text-accent-800 underline underline-offset-2"
                >
                  {run.commit.slice(0, 7)}
                </a>
              </td>
              <td className="py-2 text-12 whitespace-nowrap text-ink-500">{formatDateTime(run.createdAt)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CiRunsSection() {
  const force = useRef(false);
  const repository = configuredRepository();
  const runs = useResource("ci-runs", (signal) => {
    const forced = force.current;
    return getCiRuns(signal, { force: forced }).finally(() => {
      if (forced) force.current = false;
    });
  });
  const ci = runs.data;
  const refresh = () => {
    force.current = true;
    runs.refresh();
  };
  const link = repository && (
    <a href={actionsUrl(repository)} target="_blank" rel="noreferrer noopener" className="font-mono text-accent-800 underline underline-offset-2">
      {repository}
    </a>
  );
  return (
    <Section
      id="ci-title"
      title="Continuous integration"
      description="Recent GitHub Actions runs of this repository, read by your browser from GitHub's public API (no token). They are not part of the RAGGuard API. CI runs the checks, the offline quality gate, and a build of the Docker images; it deploys nothing."
    >
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3 text-12 text-ink-500">
          <span>{link ?? "No repository configured."}</span>
          <span className="flex items-center gap-3">
            {ci && (
              <span>
                {ci.fromCache ? "Saved" : "Fetched"} {formatDateTime(ci.fetchedAt)}
                {ci.rateLimit?.remaining != null && ` · ${ci.rateLimit.remaining} of ${ci.rateLimit.limit ?? "?"} GitHub requests left this hour`}
              </span>
            )}
            <Button size="sm" icon={RotateCw} loading={runs.loading} onClick={refresh}>
              Refresh runs
            </Button>
          </span>
        </div>

        {runs.loading && !ci && (
          <p className="text-13 text-ink-500" aria-busy="true">
            Loading runs from GitHub…
          </p>
        )}

        {runs.error && (
          <InlineAlert
            tone="error"
            title="Could not load CI runs"
            action={
              <Button size="sm" icon={RotateCw} onClick={refresh}>
                Retry
              </Button>
            }
          >
            {runs.error.message} No run status is shown, so none is assumed to have passed.
          </InlineAlert>
        )}

        {ci?.staleReason && (
          <InlineAlert tone="warning" title="These runs may be out of date">
            Showing the copy saved at {formatDateTime(ci.fetchedAt)} because GitHub could not be read now: {ci.staleReason}
          </InlineAlert>
        )}

        {ci && ci.runs.length === 0 && (
          <p className="text-13 text-ink-700">
            GitHub reports no workflow runs for {ci.repository}. Nothing is shown because nothing has run there yet.
          </p>
        )}
        {ci && ci.runs.length > 0 && <RunsTable ci={ci} />}
      </div>
    </Section>
  );
}

function Observability({ status }: { status: SystemStatus | null }) {
  const latest = status?.latest_evaluation ?? null;
  const pass = latest?.headline.find((m) => m.key === "correctness.case_pass_rate");
  const attacks = latest?.headline.find((m) => m.key === "security.attack_success_rate");
  const tracking = status?.tracking;
  return (
    <div>
      <h3 className="section-label mb-2">Offline, not part of a query</h3>
      <ol className="flex flex-col gap-1 lg:flex-row lg:items-stretch">
        <li className="flex-1 rounded-sm border border-dashed border-line-strong px-3 py-2">
          <p className="text-14 font-medium text-ink-900">Evaluation runner (CLI)</p>
          <p className="mt-1 text-12 text-ink-700">
            Runs the fixed dataset through the same pipeline code in a temporary vector store; never per user query.
          </p>
        </li>
        <li aria-hidden="true" className="flex items-center justify-center text-ink-500">
          <ArrowDown size={16} className="lg:hidden" />
          <ArrowRight size={16} className="hidden lg:block" />
        </li>
        <li className="flex-1 rounded-sm border border-dashed border-line-strong px-3 py-2">
          <p className="text-14 font-medium text-ink-900">Reports</p>
          <p className="mt-1 text-12 text-ink-700">
            {latest ? (
              <>
                {status?.evaluation_report_count} saved; latest{" "}
                <a href={routeHref("evaluation", latest.run_id)} className="font-mono text-accent-800 underline underline-offset-2">
                  {latest.run_id}
                </a>
                {pass && pass.available && ` · ${formatMetric(pass).value} cases passed`}
                {attacks && attacks.available && ` · ${formatMetric(attacks).value} attack success`}
              </>
            ) : status ? (
              "No saved report yet."
            ) : (
              "Unknown (status unavailable)."
            )}
          </p>
        </li>
        <li aria-hidden="true" className="flex items-center justify-center text-ink-500">
          <ArrowDown size={16} className="lg:hidden" />
          <ArrowRight size={16} className="hidden lg:block" />
        </li>
        <li className="flex-1 rounded-sm border border-dashed border-line-strong px-3 py-2">
          <p className="text-14 font-medium text-ink-900">Experiment tracking (MLflow)</p>
          <p className="mt-1 text-12 text-ink-700">
            {tracking ? (
              <>
                {tracking.state === "available" ? `${tracking.run_count} runs` : tracking.detail} in{" "}
                <a href={routeHref("experiments")} className="font-mono text-accent-800 underline underline-offset-2">
                  {tracking.experiment_name}
                </a>
              </>
            ) : (
              "Unknown (status unavailable)."
            )}
          </p>
        </li>
      </ol>
    </div>
  );
}

function Planned({ status }: { status: SystemStatus | null }) {
  const pending = status?.components.filter((c) => c.state === "not_implemented") ?? [];
  return (
    <ul className="space-y-2 text-13">
      {pending.map((c) => (
        <li key={c.id} className="flex flex-wrap items-baseline gap-x-3">
          <StatusTag tone="pending">Not implemented</StatusTag>
          <span className="font-medium text-ink-900">{c.label}</span>
          <span className="text-ink-700">{c.detail}</span>
        </li>
      ))}
      <li className="flex flex-wrap items-baseline gap-x-3">
        <StatusTag tone="pending">Planned</StatusTag>
        <span className="font-medium text-ink-900">Frontend redesign</span>
        <span className="text-ink-700">
          The final visual design and remaining dashboard refinements follow in a later integration stage, once the owner supplies
          visual references.
        </span>
      </li>
    </ul>
  );
}

export default function PipelineView() {
  const status = useResource("status", getSystemStatus);
  const data = status.data;
  const config = data?.configuration ?? null;
  return (
    <div className="mx-auto max-w-[1280px] space-y-6 px-4 py-6 md:px-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="max-w-[75ch] text-14 text-ink-700">
          How RAGGuard turns documents and questions into cited answers, the live status of each component, and what is not built yet.
        </p>
        <div className="flex items-center gap-3">
          {data && <span className="text-12 text-ink-500">Checked {formatDateTime(data.checked_at)}</span>}
          <Button size="sm" icon={RotateCw} loading={status.loading} onClick={status.refresh}>
            Check again
          </Button>
        </div>
      </div>

      {status.error && (
        <InlineAlert tone="error" title="Could not load the system status" action={<Button size="sm" icon={RotateCw} onClick={status.refresh}>Retry</Button>}>
          {status.error.message} Component states are unknown, so none is shown as healthy.
        </InlineAlert>
      )}

      <Section
        id="flow-title"
        title="RAG pipeline"
        description="The code path as implemented, with the current settings. It is not a record of executions: the API does not store query traces. Each answer in the Workspace shows its own evidence and timings."
      >
        <div className="space-y-4">
          <Flow label="When a document is uploaded" steps={ingestSteps(config)} start={1} />
          <Flow label="When a question is asked" steps={querySteps(config)} start={5} />
          <Observability status={data} />
        </div>
      </Section>

      <Section
        id="status-title"
        title="Component status"
        description="Healthy means a check succeeded while answering this request. Configured means settings exist but availability was not verified."
      >
        {status.loading && !data && (
          <p className="text-13 text-ink-500" aria-busy="true">
            Checking components…
          </p>
        )}
        {data && <StatusTable status={data} />}
      </Section>

      <CiRunsSection />

      <Section id="planned-title" title="Not built yet">
        <Planned status={data} />
        <p className="mt-3 text-12 text-ink-500">
          CI builds the Docker images but publishes none and deploys nothing, so no releases or deployments are shown here.
        </p>
      </Section>
    </div>
  );
}
