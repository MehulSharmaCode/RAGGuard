/** The Pipeline view's GitHub Actions section against mocked GitHub responses (no network). */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "../app/App";
import { CACHE_TTL_MS, parseRuns, runState } from "../lib/api/github";
import { systemStatus } from "./dashboardFixtures";
import { healthOk } from "./fixtures";
import { mockApi, type Route } from "./mockApi";

const REPO = "MehulSharmaCode/RAGGuard";
const RUNS = `GET /repos/${REPO}/actions/runs`;
const SHA = "e909c5e8596149d2cbba0220be7b4b9a638933a9";
const CACHE_KEY = "ragguard.ci-runs.v1";

function ghRun(id: number, overrides: Record<string, unknown> = {}) {
  return {
    id,
    name: "ragguard-ci",
    display_title: `Change number ${id}`,
    run_number: id - 100,
    run_attempt: 1,
    event: "push",
    head_branch: "main",
    head_sha: SHA,
    status: "completed",
    conclusion: "success",
    html_url: `https://github.com/${REPO}/actions/runs/${id}`,
    created_at: "2026-10-26T10:00:00Z",
    updated_at: "2026-10-26T10:12:00Z",
    ...overrides,
  };
}

const response =
  (status: number, body: unknown, headers: Record<string, string> = {}): Route =>
  () =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

const runsBody = (runs: unknown[]) => ({ total_count: runs.length, workflow_runs: runs });

function open(routes: Record<string, Route | Route[]>) {
  window.location.hash = "#/pipeline";
  const api = mockApi({
    "GET /health": { body: healthOk },
    "GET /documents": { body: { documents: [] } },
    "GET /system/status": { body: systemStatus },
    ...routes,
  });
  const user = userEvent.setup();
  render(<App />);
  return { api, user };
}

const ciSection = () => screen.getByRole("region", { name: "Continuous integration" });
const rowOf = (text: string) =>
  within(screen.getByRole("table", { name: "Recent workflow runs" }))
    .getAllByRole("row")
    .find((r) => r.textContent?.includes(text))!;

function seedCache(ageMs: number, runs: unknown[] = [ghRun(201)]) {
  const parsed = parseRuns(runsBody(runs), REPO)!;
  window.sessionStorage.setItem(
    CACHE_KEY,
    JSON.stringify({ repository: REPO, fetchedAt: new Date(Date.now() - ageMs).toISOString(), runs: parsed, rateLimit: null }),
  );
}

describe("CI runs in the Pipeline view", () => {
  it("lists real runs with their outcome, trigger, commit and a link to the GitHub run page", async () => {
    const { api } = open({
      [RUNS]: {
        body: runsBody([
          ghRun(104, { status: "in_progress", conclusion: null, display_title: "Add the gate" }),
          ghRun(103, { conclusion: "failure", display_title: "Lower a threshold", event: "pull_request", head_branch: "tune" }),
          ghRun(102, { conclusion: "cancelled" }),
          ghRun(101, { conclusion: "success" }),
        ]),
      },
    });
    expect(await screen.findByRole("table", { name: "Recent workflow runs" })).toBeInTheDocument();
    expect(rowOf("#4")).toHaveTextContent("Running");
    expect(rowOf("#3")).toHaveTextContent("Failed");
    expect(rowOf("#3")).toHaveTextContent("pull request");
    expect(rowOf("#3")).toHaveTextContent("tune");
    expect(rowOf("#2")).toHaveTextContent("Cancelled");
    expect(rowOf("#1")).toHaveTextContent("Passed");
    expect(rowOf("#1")).toHaveTextContent("e909c5e");
    expect(within(rowOf("#3")).getByRole("link", { name: "Open run 3 of ragguard-ci on GitHub" })).toHaveAttribute(
      "href",
      `https://github.com/${REPO}/actions/runs/103`,
    );
    expect(within(rowOf("#3")).getByRole("link", { name: "e909c5e" })).toHaveAttribute("href", `https://github.com/${REPO}/commit/${SHA}`);
    expect(ciSection()).toHaveTextContent("it deploys nothing");

    // One anonymous request: no credentials of any kind, and the page does not poll.
    expect(api.count(RUNS)).toBe(1);
    const call = api.calls.find((c) => c.path.endsWith("/actions/runs"))!;
    expect(call.search).toBe("?per_page=10");
    expect(call.init?.headers).toEqual({ Accept: "application/vnd.github+json" });
    expect(call.init?.credentials).toBeUndefined();
  });

  it("states that nothing has run when GitHub reports no runs", async () => {
    open({ [RUNS]: { body: runsBody([]) } });
    expect(await screen.findByText(/GitHub reports no workflow runs for MehulSharmaCode\/RAGGuard/)).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Recent workflow runs" })).not.toBeInTheDocument();
    expect(screen.queryByText("Passed")).not.toBeInTheDocument();
  });

  it("shows a loading state first", async () => {
    open({ [RUNS]: "pending" });
    expect(await screen.findByText("Loading runs from GitHub…")).toHaveAttribute("aria-busy", "true");
  });

  it("shows no status at all when GitHub cannot be reached", async () => {
    open({ [RUNS]: "network-error" });
    expect(await screen.findByText("Could not load CI runs")).toBeInTheDocument();
    expect(ciSection()).toHaveTextContent("Cannot reach api.github.com");
    expect(ciSection()).toHaveTextContent("none is assumed to have passed");
    expect(screen.queryByRole("table", { name: "Recent workflow runs" })).not.toBeInTheDocument();
    expect(screen.queryByText("Passed")).not.toBeInTheDocument();
  });

  it("explains an exhausted anonymous rate limit", async () => {
    const reset = String(Math.floor(Date.now() / 1000) + 1800);
    open({
      [RUNS]: response(403, { message: "API rate limit exceeded" }, { "x-ratelimit-limit": "60", "x-ratelimit-remaining": "0", "x-ratelimit-reset": reset }),
    });
    expect(await screen.findByText("Could not load CI runs")).toBeInTheDocument();
    expect(ciSection()).toHaveTextContent("rate limit is used up (60 requests per hour per network)");
    expect(ciSection()).toHaveTextContent("It resets at");
  });

  it("treats HTTP 429 as a rate limit", async () => {
    open({ [RUNS]: response(429, { message: "slow down" }) });
    expect(await screen.findByText(/rate limit is used up/)).toBeInTheDocument();
  });

  it("explains a missing or private repository", async () => {
    open({ [RUNS]: response(404, { message: "Not Found" }) });
    expect(await screen.findByText(/has no public Actions data for MehulSharmaCode\/RAGGuard \(HTTP 404\)/)).toBeInTheDocument();
  });

  it("rejects a response that does not match the expected format instead of guessing", async () => {
    open({ [RUNS]: { body: runsBody([ghRun(101), { id: 5, status: "completed" }]) } });
    expect(await screen.findByText(/did not match the expected format, so no runs are shown/)).toBeInTheDocument();
    expect(screen.queryByRole("table", { name: "Recent workflow runs" })).not.toBeInTheDocument();
  });

  it("rejects a run whose link does not point at this repository", async () => {
    open({ [RUNS]: { body: runsBody([ghRun(101, { html_url: "https://evil.example/MehulSharmaCode/RAGGuard/actions/runs/101" })]) } });
    expect(await screen.findByText(/did not match the expected format/)).toBeInTheDocument();
    expect(document.querySelector('a[href*="evil.example"]')).toBeNull();
  });

  it("rejects a body that is not JSON", async () => {
    open({ [RUNS]: () => new Response("<html>proxy error</html>", { status: 200 }) });
    expect(await screen.findByText(/did not match the expected format/)).toBeInTheDocument();
  });

  it("reuses a recent copy without asking GitHub again", async () => {
    seedCache(60_000, [ghRun(201, { conclusion: "failure" })]);
    const { api } = open({ [RUNS]: { body: runsBody([]) } });
    expect(await screen.findByRole("table", { name: "Recent workflow runs" })).toBeInTheDocument();
    expect(rowOf("#101")).toHaveTextContent("Failed");
    expect(ciSection()).toHaveTextContent("Saved");
    expect(api.count(RUNS)).toBe(0);
  });

  it("asks GitHub again once the copy is older than the cache lifetime, and on Refresh", async () => {
    seedCache(CACHE_TTL_MS + 1000, [ghRun(201, { conclusion: "failure" })]);
    const { api, user } = open({ [RUNS]: { body: runsBody([ghRun(301, { conclusion: "success" })]) } });
    await waitFor(() => expect(rowOf("#201")).toHaveTextContent("Passed"));
    expect(api.count(RUNS)).toBe(1);
    expect(ciSection()).toHaveTextContent("Fetched");

    await user.click(within(ciSection()).getByRole("button", { name: "Refresh runs" }));
    await waitFor(() => expect(api.count(RUNS)).toBe(2));
  });

  it("forces a request on Refresh even when the copy is recent", async () => {
    seedCache(1000);
    const { api, user } = open({ [RUNS]: { body: runsBody([ghRun(301)]) } });
    await screen.findByRole("table", { name: "Recent workflow runs" });
    expect(api.count(RUNS)).toBe(0);
    await user.click(within(ciSection()).getByRole("button", { name: "Refresh runs" }));
    await waitFor(() => expect(api.count(RUNS)).toBe(1));
  });

  it("labels an older copy as possibly out of date when GitHub cannot be reached", async () => {
    seedCache(CACHE_TTL_MS * 4, [ghRun(201, { conclusion: "failure" })]);
    open({ [RUNS]: "network-error" });
    expect(await screen.findByText("These runs may be out of date")).toBeInTheDocument();
    expect(ciSection()).toHaveTextContent("because GitHub could not be read now: Cannot reach api.github.com");
    expect(rowOf("#101")).toHaveTextContent("Failed"); // still the real, last known outcome
    expect(screen.queryByText("Could not load CI runs")).not.toBeInTheDocument();
  });

  it("ignores a cache entry that was tampered with", async () => {
    window.sessionStorage.setItem(
      CACHE_KEY,
      JSON.stringify({ repository: REPO, fetchedAt: new Date().toISOString(), runs: [{ id: 1, state: "success", url: "https://evil.example/x" }], rateLimit: null }),
    );
    const { api } = open({ [RUNS]: { body: runsBody([ghRun(301)]) } });
    await screen.findByRole("table", { name: "Recent workflow runs" });
    expect(api.count(RUNS)).toBe(1);
    expect(document.querySelector('a[href*="evil.example"]')).toBeNull();
  });

  it("reports the remaining anonymous requests when GitHub says", async () => {
    open({
      [RUNS]: response(200, runsBody([ghRun(101)]), { "x-ratelimit-limit": "60", "x-ratelimit-remaining": "41", "x-ratelimit-reset": "1893456000" }),
    });
    expect(await screen.findByText(/41 of 60 GitHub requests left this hour/)).toBeInTheDocument();
  });
});

describe("run state mapping", () => {
  it.each([
    ["completed", "success", "success"],
    ["completed", "failure", "failure"],
    ["completed", "timed_out", "failure"],
    ["completed", "startup_failure", "failure"],
    ["completed", "cancelled", "cancelled"],
    ["completed", "action_required", "action_required"],
    ["completed", "skipped", "other"],
    ["completed", null, "other"],
    ["in_progress", null, "in_progress"],
    ["queued", null, "queued"],
    ["waiting", null, "queued"],
    ["something_new", null, "other"],
  ] as const)("%s / %s is %s", (status, conclusion, expected) => {
    expect(runState(status, conclusion)).toBe(expected);
  });

  it("never turns an unknown outcome into a pass", () => {
    expect(runState("completed", "neutral")).not.toBe("success");
    expect(runState("completed", "stale")).not.toBe("success");
  });
});

describe("response validation", () => {
  it("accepts a well-formed response and an empty list", () => {
    expect(parseRuns(runsBody([ghRun(101)]), REPO)).toHaveLength(1);
    expect(parseRuns(runsBody([]), REPO)).toEqual([]);
  });

  it.each([
    ["not an object", "text"],
    ["no workflow_runs", { total_count: 0 }],
    ["workflow_runs not an array", { workflow_runs: {} }],
    ["a run that is not an object", runsBody([7])],
    ["a non-hex commit", runsBody([ghRun(1, { head_sha: "main" })])],
    ["a missing status", runsBody([ghRun(1, { status: null })])],
    ["a non-numeric id", runsBody([ghRun(1, { id: "1" })])],
    ["an unparseable date", runsBody([ghRun(1, { created_at: "yesterday" })])],
    ["a link to another run", runsBody([ghRun(1, { html_url: `https://github.com/${REPO}/actions/runs/2` })])],
    ["a link to another repository", runsBody([ghRun(1, { html_url: "https://github.com/someone/else/actions/runs/1" })])],
  ])("rejects %s", (_, payload) => {
    expect(parseRuns(payload, REPO)).toBeNull();
  });

  it("keeps GitHub's own words for outcomes it has no label for", async () => {
    open({ [RUNS]: { body: runsBody([ghRun(101, { conclusion: "skipped" })]) } });
    await screen.findByRole("table", { name: "Recent workflow runs" });
    expect(rowOf("#1")).toHaveTextContent("skipped");
    expect(rowOf("#1")).not.toHaveTextContent("Passed");
  });
});
