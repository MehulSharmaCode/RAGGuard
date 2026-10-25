/** Conversation persistence across navigation and reloads (mocked HTTP, no live backend). */

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "../app/App";
import { STORAGE_KEY } from "../features/chat/conversationStorage";
import { evaluationList, finalDetail, FINAL_ID, runList, comparison, systemStatus } from "./dashboardFixtures";
import { answered, belowThreshold, handbook, healthOk, notes } from "./fixtures";
import { json, mockApi, type Route } from "./mockApi";

const dashboards: Record<string, Route | Route[]> = {
  "GET /health": { body: healthOk },
  "GET /documents": { body: { documents: [handbook, notes] } },
  "GET /evaluations": { body: evaluationList },
  [`GET /evaluations/${FINAL_ID}`]: { body: finalDetail },
  "GET /experiments/runs": { body: runList },
  "GET /experiments/compare": { body: comparison },
  "GET /system/status": { body: systemStatus },
};

function setup(routes: Record<string, Route | Route[]>) {
  const api = mockApi({ ...dashboards, ...routes });
  const user = userEvent.setup({ applyAccept: false });
  const view = render(<App />);
  return { api, user, view };
}

type User = ReturnType<typeof userEvent.setup>;

async function ask(user: User, question: string) {
  const box = await screen.findByRole("textbox", { name: "Question" });
  await waitFor(() => expect(box).toBeEnabled());
  await user.type(box, `${question}{Enter}`);
}

async function go(user: User, name: "Workspace" | "Evaluation" | "Experiments" | "Pipeline") {
  const nav = screen.getAllByRole("navigation", { name: "Primary" })[0]!;
  await user.click(within(nav).getByRole("link", { name }));
}

async function visitAllViews(user: User) {
  await go(user, "Evaluation");
  expect(await screen.findByText("77 of 85 cases passed (90.6%) · 5 of 32 attack cases succeeded (15.6%)")).toBeInTheDocument();
  await go(user, "Experiments");
  expect(await screen.findByRole("table", { name: "Tracked evaluation runs" })).toBeInTheDocument();
  await go(user, "Pipeline");
  expect(await screen.findByRole("table", { name: "Component status" })).toBeInTheDocument();
  await go(user, "Workspace");
}

const questions = () => screen.getAllByRole("article").map((a) => a.getAttribute("aria-label"));

describe("conversation survives navigation", () => {
  it("keeps every turn, its citations, fallback and failure states across all views", async () => {
    const { api, user } = setup({
      "POST /query": [
        { body: answered },
        { body: belowThreshold },
        { status: 503, body: { error: { code: "generation_unavailable", message: "The Ollama service is not reachable." } } },
      ],
    });
    await ask(user, "How much annual leave?");
    await screen.findByRole("region", { name: "Answer" });
    await ask(user, "What is the dress code?");
    await screen.findByRole("region", { name: "Insufficient evidence" });
    await ask(user, "Who leads Kestrel?");
    await screen.findByRole("alert");

    await visitAllViews(user);

    expect(questions()).toEqual([
      "Question: How much annual leave?",
      "Question: What is the dress code?",
      "Question: Who leads Kestrel?",
    ]);
    expect(screen.getByRole("region", { name: "Answer" })).toHaveTextContent("Employees receive 25 days of paid annual leave");
    expect(screen.getByRole("region", { name: "Answer" })).toHaveTextContent("qwen3.5:9b via ollama");
    expect(screen.getByRole("region", { name: "Insufficient evidence" })).toHaveTextContent("below the 0.350 evidence threshold");
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Request failed — no answer was produced");
    expect(alert).toHaveTextContent("generation_unavailable");
    expect(api.count("POST /query")).toBe(3); // nothing was re-sent by navigating

    // A citation still opens its passage after returning.
    const answer = screen.getByRole("region", { name: "Answer" });
    await user.click(within(answer).getAllByRole("button", { name: "Source S1: handbook.pdf, p. 2" })[0]!);
    const items = within(screen.getByRole("list", { name: "Evidence passages" })).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Employees receive 25 days of paid annual leave per calendar year.");
    expect(within(items[0]!).getByRole("button", { pressed: true })).toBeInTheDocument();
  });

  it("keeps the selected citation when navigating away and back", async () => {
    const { user } = setup({ "POST /query": { body: answered } });
    await ask(user, "Leave?");
    const answer = await screen.findByRole("region", { name: "Answer" });
    await user.click(within(answer).getAllByRole("button", { name: "Source S1: handbook.pdf, p. 2" })[0]!);
    await go(user, "Pipeline");
    await screen.findByRole("table", { name: "Component status" });
    await go(user, "Workspace");
    const evidence = await screen.findByRole("list", { name: "Evidence passages" });
    expect(within(within(evidence).getAllByRole("listitem")[0]!).getByRole("button", { pressed: true })).toHaveTextContent("handbook.pdf");
  });

  it("completes a request that was pending during navigation exactly once", async () => {
    let release: (response: Response) => void = () => undefined;
    const gate = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const { api, user } = setup({ "POST /query": () => gate });
    await ask(user, "Pending question?");
    expect(await screen.findByText("Retrieving evidence and waiting for the answer…")).toBeInTheDocument();

    await go(user, "Evaluation");
    await screen.findByText(/77 of 85 cases passed/);
    await act(async () => release(json(200, answered)));
    await go(user, "Experiments");
    await screen.findByRole("table", { name: "Tracked evaluation runs" });
    await go(user, "Workspace");

    expect(await screen.findByRole("region", { name: "Answer" })).toHaveTextContent("25 days");
    expect(questions()).toEqual(["Question: Pending question?"]);
    expect(screen.queryByText("Retrieving evidence and waiting for the answer…")).not.toBeInTheDocument();
    expect(api.count("POST /query")).toBe(1);
  });

  it("clears the conversation after confirmation, including the stored copy", async () => {
    const { user } = setup({ "POST /query": { body: answered } });
    await ask(user, "Leave?");
    await screen.findByRole("region", { name: "Answer" });
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toContain("Leave?");
    expect(screen.getByText(/Kept in this browser tab until you clear it or close the tab/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear conversation" }));
    const confirm = screen.getByRole("group", { name: "Confirm clearing the conversation" });
    expect(confirm).toHaveTextContent("Remove this conversation (1 question)? Other conversations are kept.");
    await user.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(questions()).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "Clear conversation" }));
    await user.click(within(screen.getByRole("group", { name: "Confirm clearing the conversation" })).getByRole("button", { name: "Clear" }));
    expect(screen.queryAllByRole("article")).toHaveLength(0);
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(screen.getByRole("heading", { name: "Ask about your documents" })).toBeInTheDocument();
    await go(user, "Pipeline");
    await screen.findByRole("table", { name: "Component status" });
    await go(user, "Workspace");
    expect(screen.queryAllByRole("article")).toHaveLength(0);
  });

  it("drops a pending request when the conversation is cleared", async () => {
    let release: (response: Response) => void = () => undefined;
    const gate = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const { user } = setup({ "POST /query": () => gate });
    await ask(user, "Pending question?");
    await user.click(await screen.findByRole("button", { name: "Clear conversation" }));
    await user.click(within(screen.getByRole("group", { name: "Confirm clearing the conversation" })).getByRole("button", { name: "Clear" }));
    await act(async () => release(json(200, answered)));
    expect(screen.queryAllByRole("article")).toHaveLength(0);
  });
});

describe("conversation survives a reload of the tab", () => {
  it("restores answered turns with working citations", async () => {
    const first = setup({ "POST /query": [{ body: answered }, { body: belowThreshold }] });
    await ask(first.user, "Leave?");
    await screen.findByRole("region", { name: "Answer" });
    await ask(first.user, "Dress code?");
    await screen.findByRole("region", { name: "Insufficient evidence" });
    first.view.unmount();

    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByRole("region", { name: "Answer" })).toHaveTextContent("25 days of paid annual leave");
    expect(screen.getByRole("region", { name: "Insufficient evidence" })).toBeInTheDocument();
    expect(questions()).toEqual(["Question: Leave?", "Question: Dress code?"]);
    await user.click(within(screen.getByRole("region", { name: "Answer" })).getAllByRole("button", { name: "Source S1: handbook.pdf, p. 2" })[0]!);
    const items = within(screen.getByRole("list", { name: "Evidence passages" })).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Employees receive 25 days");
  });

  it("marks a request interrupted by the reload as failed, with retry", async () => {
    const first = setup({ "POST /query": ["pending", { body: answered }] });
    await ask(first.user, "Interrupted?");
    await screen.findByText("Retrieving evidence and waiting for the answer…");
    first.view.unmount();

    const user = userEvent.setup();
    render(<App />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The page was reloaded before the answer arrived");
    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("region", { name: "Answer" })).toBeInTheDocument();
    expect(questions()).toEqual(["Question: Interrupted?"]);
  });

  it("ignores stored data in an unknown or corrupted format", async () => {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 99, turns: [{ id: "x" }] }));
    setup({});
    expect(await screen.findByRole("heading", { name: "Ask about your documents" })).toBeInTheDocument();
    expect(screen.queryAllByRole("article")).toHaveLength(0);
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull();

    window.sessionStorage.setItem(STORAGE_KEY, "{not json");
    render(<App />);
    await waitFor(() => expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull());
  });

  it("does not store uploaded files or document lists, only the conversations", async () => {
    const { user } = setup({ "POST /query": { body: answered } });
    await ask(user, "Leave?");
    await screen.findByRole("region", { name: "Answer" });
    type StoredThread = { signature: string; turns: { state: { response: { sources: unknown[] } } }[] };
    const stored = JSON.parse(window.sessionStorage.getItem(STORAGE_KEY)!) as { threads: StoredThread[] };
    expect(Object.keys(stored)).toEqual(["version", "threads", "activeThreadId"]);
    expect(stored.threads).toHaveLength(1);
    expect(Object.keys(stored.threads[0]!)).toEqual(["id", "signature", "scope", "label", "createdAt", "updatedAt", "turns", "selection"]);
    expect(stored.threads[0]!.signature).toBe(`all:${[handbook.document_id, notes.document_id].sort().join(",")}`);
    expect(stored.threads[0]!.turns).toHaveLength(1);
    expect(stored.threads[0]!.turns[0]!.state.response.sources).toHaveLength(2); // the passages supplied with this answer only
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull(); // never kept beyond the tab
  });
});
