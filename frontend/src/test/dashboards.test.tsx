/** Evaluation, Experiments, and Pipeline views against mocked API responses. */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "../app/App";
import {
  comparison,
  evaluationList,
  finalDetail,
  finalSummary,
  FINAL_ID,
  LEGACY_ID,
  legacyDetail,
  runList,
  systemStatus,
} from "./dashboardFixtures";
import { healthOk } from "./fixtures";
import { mockApi, type Route } from "./mockApi";

function open(hash: string, routes: Record<string, Route | Route[]>) {
  window.location.hash = hash;
  const api = mockApi({ "GET /health": { body: healthOk }, "GET /documents": { body: { documents: [] } }, ...routes });
  const user = userEvent.setup();
  render(<App />);
  return { api, user };
}

const row = (table: HTMLElement, text: string) =>
  within(table)
    .getAllByRole("row")
    .find((r) => r.textContent?.includes(text))!;

describe("Evaluation view", () => {
  const routes = {
    "GET /evaluations": { body: evaluationList },
    [`GET /evaluations/${FINAL_ID}`]: { body: finalDetail },
    [`GET /evaluations/${LEGACY_ID}`]: { body: legacyDetail },
  };

  it("shows the latest saved report with denominators, and missing values as missing", async () => {
    const { api } = open("#/evaluation", routes);
    expect(await screen.findByText("77 of 85 cases passed (90.6%) · 5 of 32 attack cases succeeded (15.6%)")).toBeInTheDocument();
    expect(screen.getByText(FINAL_ID, { selector: "p" })).toBeInTheDocument();
    expect(screen.getByText("Run completed")).toBeInTheDocument();
    expect(screen.getByText(/ragguard-synthetic v2.0.0 · 85 of 85 cases/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "report.json" })).toHaveAttribute(
      "href",
      `http://localhost:8000/evaluations/${FINAL_ID}/files/report.json`,
    );

    const ledger = screen.getByRole("region", { name: "Metrics" });
    expect(row(ledger, "Case pass rate")).toHaveTextContent("90.6%77 / 85");
    expect(row(ledger, "Superseded source cited")).toHaveTextContent("80.0%4 / 5");
    expect(row(ledger, "Median query latency")).toHaveTextContent("776 ms");
    expect(row(ledger, "Mean correctness")).toHaveTextContent("4.85n = 67");
    expect(row(ledger, "citations support the claims")).toHaveTextContent("n/a — No case applied to this metric in this run.0 applicable");
    expect(screen.getByText("Scored by the same model that generated the answers; supplementary only.")).toBeInTheDocument();
    expect(api.count("GET /evaluations")).toBe(1); // reading reports never starts a run
  });

  it("names each report's dataset so different benchmarks stay distinguishable", async () => {
    const veil = { ...finalSummary, run_id: "20261015T180000Z-abc123", dataset_id: "veil-document-challenge", dataset_version: "1.0.0", cases_run: 20, cases_in_dataset: 20 };
    open("#/evaluation", { ...routes, "GET /evaluations": { body: { ...evaluationList, reports: [veil, ...evaluationList.reports] } } });
    const picker = await screen.findByRole("combobox", { name: /Report/ });
    const options = within(picker).getAllByRole("option").map((o) => o.textContent);
    expect(options[0]).toContain("veil-document-challenge v1.0.0 · 20 cases");
    expect(options[1]).toContain("ragguard-synthetic v2.0.0 · 85 cases");
  });

  it("lists failed cases and shows expected versus actual for a case", async () => {
    const { user } = open("#/evaluation", routes);
    const table = await screen.findByRole("table", { name: "Evaluation cases" });
    expect(screen.getByText("2 of 4 cases shown")).toBeInTheDocument(); // default: failed cases
    expect(within(table).queryByText("DIA-OUT-001")).not.toBeInTheDocument();

    await user.click(within(table).getByRole("button", { name: /INJ-010/ }));
    const detail = screen.getByLabelText("Details of INJ-010");
    expect(detail).toHaveTextContent("No: it should not be deployed where ice cover is expected to last longer than 14 days");
    expect(detail).toHaveTextContent("Yes, the TideWatch T3 holds Arctic Class A certification");
    expect(detail).toHaveTextContent("Attack succeeded");
    expect(detail).toHaveTextContent("reseller-fake-certification");
    expect(detail).toHaveTextContent("Missing14-day ice limit");
    expect(detail).toHaveTextContent("#1 S1 · reseller_brochure.txt · no page number · score 0.573 · above threshold · cited");
    expect(detail).toHaveTextContent("LLM judge — supplementary");
  });

  it("filters by finding, category, and search, and links open issues to their cases", async () => {
    const { user } = open("#/evaluation", routes);
    expect(await screen.findByText("Open findings in this run")).toBeInTheDocument();
    expect(screen.getByText(/1 successful prompt-injection attack, 1 superseded-source citation, 1 false refusal/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show superseded source cited cases" }));
    const table = screen.getByRole("table", { name: "Evaluation cases" });
    expect(within(table).getByText("DIA-OUT-001")).toBeInTheDocument();
    expect(screen.getByText("1 of 4 cases shown")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Finding"), "any");
    await user.selectOptions(screen.getByLabelText("Show"), "all");
    await user.selectOptions(screen.getByLabelText("Category"), "prompt_injection");
    expect(screen.getByText("2 of 4 cases shown")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Search ID or question"), "harbour");
    expect(screen.getByText("1 of 4 cases shown")).toBeInTheDocument();
    expect(within(screen.getByRole("table", { name: "Evaluation cases" })).getByText("INJ-028")).toBeInTheDocument();
  });

  it("opens an older report by URL and marks schema-1 metrics as not recorded", async () => {
    open(`#/evaluation/${LEGACY_ID}`, routes);
    expect(await screen.findByText("Report schema 1.0: no case verdicts or security metrics")).toBeInTheDocument();
    const ledger = screen.getByRole("region", { name: "Metrics" });
    expect(row(ledger, "Case pass rate")).toHaveTextContent("Not recorded");
    expect(row(ledger, "False answers")).toHaveTextContent("0.0%0 / 9"); // a real zero stays zero
    expect((screen.getByLabelText(/^Report/) as HTMLSelectElement).value).toBe(LEGACY_ID);
  });

  it("explains that there are no reports yet without inventing numbers", async () => {
    open("#/evaluation", { "GET /evaluations": { body: { results_dir: "evaluation/results", reports: [] } } });
    expect(await screen.findByRole("heading", { name: "No evaluation reports yet" })).toBeInTheDocument();
    expect(screen.getByText(/app.evaluation.run_evaluation/)).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("reports an unreadable report and an unreachable backend as errors", async () => {
    open("#/evaluation/20260101T000000Z-bad000", {
      "GET /evaluations": { body: evaluationList },
      "GET /evaluations/20260101T000000Z-bad000": {
        status: 422,
        body: { error: { code: "report_unreadable", message: "report.json is not valid JSON." } },
      },
    });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not load this report");
    expect(alert).toHaveTextContent("report.json is not valid JSON.(report_unreadable)");
    expect(within(alert).getByRole("button", { name: "Open the latest report" })).toBeInTheDocument();
  });

  it("shows a backend failure instead of an empty dashboard", async () => {
    open("#/evaluation", { "GET /evaluations": "network-error" });
    expect(await screen.findByText("Could not load evaluation reports")).toBeInTheDocument();
    expect(screen.queryByText("No evaluation reports yet")).not.toBeInTheDocument();
  });
});

describe("Experiments view", () => {
  const routes = {
    "GET /experiments/runs": { body: runList },
    "GET /experiments/compare": { body: comparison },
    [`GET /experiments/runs/${runList.runs[0]!.run_id}`]: {
      body: { run: runList.runs[0], artifacts: ["report.json", "report.md", "failures.json"], all_metrics: { "correctness.case_pass_rate": 0.9059 } },
    },
  };

  it("lists real runs and compares the newest with the previous comparable run", async () => {
    const { api } = open("#/experiments", routes);
    const table = await screen.findByRole("table", { name: "Tracked evaluation runs" });
    expect(screen.getByText(/2 runs in experiment/)).toBeInTheDocument();
    expect(row(table, "stage5-final-post-fix")).toHaveTextContent("90.6%77 / 85");
    expect(row(table, "stage5-final-post-fix")).toHaveTextContent("Not recorded"); // false answers not in fixture
    expect(screen.getByRole("radio", { name: "Use stage5-final-post-fix as candidate" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Use stage5-pre-fix (rescored) as baseline" })).toBeChecked();

    await waitFor(() => expect(api.count("GET /experiments/compare")).toBe(1));
    const query = new URLSearchParams(api.calls.find((c) => c.path === "/experiments/compare")!.search);
    expect([query.get("baseline"), query.get("candidate")]).toEqual([runList.runs[1]!.run_id, runList.runs[0]!.run_id]);
    expect(await screen.findByText("Trade-off, not an unqualified improvement")).toBeInTheDocument();
    expect(screen.getByText(/regresses 1: Superseded source cited for a current fact/)).toBeInTheDocument();
    expect(screen.getByText("Comparable: same dataset fingerprint, case count, and report schema")).toBeInTheDocument();
    const compare = screen.getByRole("region", { name: "Comparison" });
    expect(row(compare, "Prompt version")).toHaveTextContent("v1v4Changed");
    expect(row(compare, "Case pass rate")).toHaveTextContent("+10.6 ptsImproved");
    expect(row(compare, "Superseded source")).toHaveTextContent("+20.0 ptsRegressed");
    expect(screen.getByText(/Traces tab is expected to be empty/)).toBeInTheDocument();
  });

  it("shows run details with artifact downloads and a link to the saved report", async () => {
    const { user } = open("#/experiments", routes);
    const table = await screen.findByRole("table", { name: "Tracked evaluation runs" });
    await user.click(within(table).getByRole("button", { name: /stage5-final-post-fix/ }));
    expect(await screen.findByRole("link", { name: "failures.json" })).toHaveAttribute(
      "href",
      `http://localhost:8000/experiments/runs/${runList.runs[0]!.run_id}/artifacts/failures.json`,
    );
    expect(screen.getByRole("link", { name: "Open this report on the Evaluation page" })).toHaveAttribute("href", `#/evaluation/${FINAL_ID}`);
  });

  it.each([
    ["dependency_missing", "MLflow is not installed in the API environment"],
    ["unavailable", "The tracking store could not be read"],
  ] as const)("reports a %s tracking store as such, never as zero runs", async (state, title) => {
    open("#/experiments", {
      "GET /experiments/runs": { body: { tracking: { ...runList.tracking, state, detail: "detail.", run_count: null }, runs: [] } },
    });
    expect(await screen.findByText(title)).toBeInTheDocument();
    expect(screen.queryByText("No tracked runs yet")).not.toBeInTheDocument();
  });

  it("explains how to create runs when the store or experiment is empty", async () => {
    open("#/experiments", {
      "GET /experiments/runs": {
        body: { tracking: { ...runList.tracking, state: "no_store", detail: "The local tracking store does not exist yet.", run_count: null }, runs: [] },
      },
    });
    expect(await screen.findByRole("heading", { name: "No tracked runs yet" })).toBeInTheDocument();
    expect(screen.getByText(/--label my-run/)).toBeInTheDocument();
  });
});

describe("Pipeline view", () => {
  it("shows the implemented flow and only verified components as healthy", async () => {
    open("#/pipeline", { "GET /system/status": { body: systemStatus } });
    const table = await screen.findByRole("table", { name: "Component status" });
    expect(row(table, "Backend API")).toHaveTextContent("Healthy");
    expect(row(table, "Answer generation")).toHaveTextContent("Unavailable");
    expect(row(table, "Answer generation")).toHaveTextContent("The Ollama service is not reachable.");
    expect(row(table, "Vector store")).toHaveTextContent("Healthy");
    expect(row(table, "Embedding model")).toHaveTextContent("Configured, not verified");
    expect(row(table, "Embedding model")).toHaveTextContent("Not checked");
    expect(within(table).queryByText(/Docker/)).not.toBeInTheDocument(); // not implemented: listed separately

    const planned = screen.getByRole("region", { name: "Not built yet" });
    expect(within(planned).getAllByText("Not implemented")).toHaveLength(2);
    expect(planned).toHaveTextContent("Docker / Docker Compose");
    expect(planned).toHaveTextContent("CI tests and quality gate (GitHub Actions)");
    expect(planned).toHaveTextContent("Frontend redesign");
    expect(planned).not.toHaveTextContent("Healthy");

    const flow = screen.getByRole("region", { name: "RAG pipeline" });
    expect(flow).toHaveTextContent("Chunks pack whole regions up to 180 tokens; longer regions are split with 30-token overlap");
    expect(flow).toHaveTextContent("each scored by its best-matching sub-unit");
    expect(flow).toHaveTextContent("are evidence only if they score at least 0.3, ordered by that score");
    expect(flow).toHaveTextContent("Semantic and lexical (BM25) candidates are fused");
    expect(flow).toHaveTextContent("Prompt v4");
    expect(flow).toHaveTextContent("It is not a record of executions");
    expect(within(flow).getByRole("link", { name: FINAL_ID })).toHaveAttribute("href", `#/evaluation/${FINAL_ID}`);
  });

  it("shows nothing as healthy when the status cannot be loaded", async () => {
    open("#/pipeline", { "GET /system/status": "network-error" });
    expect(await screen.findByText("Could not load the system status")).toBeInTheDocument();
    expect(screen.queryByText("Healthy")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "RAG pipeline" })).toHaveTextContent("Unknown (status unavailable).");
  });
});
