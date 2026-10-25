/** Conversations separated by document context (D-065): mocked HTTP, no live backend. */

import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "../app/App";
import { LEGACY_STORAGE_KEY, STORAGE_KEY } from "../features/chat/conversationStorage";
import type { DocumentInfo, QueryResponse } from "../types/api";
import { answered, belowThreshold, handbook, healthOk, notes } from "./fixtures";
import { json, mockApi, type Route } from "./mockApi";

const AGRI_ID = "0c7e1d6a-3f5b-4f0e-9a6d-2b1c8e4f7a90";
const agrisense: DocumentInfo = { ...notes, document_id: AGRI_ID, filename: "agrisense.pdf", ingested_at: "2026-10-16T09:00:00+00:00" };

const base: Record<string, Route | Route[]> = { "GET /health": { body: healthOk } };

function setup(routes: Record<string, Route | Route[]>) {
  const api = mockApi({ ...base, ...routes });
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

const questions = () => screen.queryAllByRole("article").map((a) => a.getAttribute("aria-label"));
const picker = () => screen.getByRole("combobox", { name: /Conversations in this tab/ });
const options = () => within(picker()).getAllByRole("option").map((o) => o.textContent ?? "");

async function openThreadContaining(user: User, text: string) {
  const option = within(picker()).getAllByRole("option").find((o) => o.textContent?.includes(text));
  if (!option) throw new Error(`no conversation option containing ${text}`);
  await user.selectOptions(picker(), option);
}

const fileInput = () => screen.getByLabelText("Upload a PDF or TXT document") as HTMLInputElement;

describe("conversations are separated by document context", () => {
  it("starts a new conversation when an upload changes the corpus and keeps the earlier one", async () => {
    const { api, user } = setup({
      "GET /documents": [{ body: { documents: [handbook] } }, { body: { documents: [handbook, agrisense] } }],
      "POST /ingest": { status: 201, body: { ...agrisense, pages_with_text: 22 } },
      "POST /query": [{ body: answered }, { body: belowThreshold }],
    });
    await ask(user, "SIH question?");
    await screen.findByRole("region", { name: "Answer" });

    await user.upload(fileInput(), new File(["%PDF-1.4"], "agrisense.pdf", { type: "application/pdf" }));
    await screen.findByText("agrisense.pdf", { selector: "p, span" }).catch(() => undefined);
    await waitFor(() => expect(questions()).toEqual([]));
    expect(screen.getByRole("status")).toHaveTextContent("New conversation for the current documents");
    expect(options().some((o) => o.includes("(other documents)") && o.includes("1 question"))).toBe(true);

    await ask(user, "AgriSense question?");
    await screen.findByRole("region", { name: "Insufficient evidence" });
    expect(questions()).toEqual(["Question: AgriSense question?"]);
    expect(options()).toHaveLength(2);

    // The earlier conversation is still there, as history, and is never sent to the backend.
    await openThreadContaining(user, "(other documents)");
    expect(questions()).toEqual(["Question: SIH question?"]);
    expect(screen.getByText("Earlier conversation with a different set of documents")).toBeInTheDocument();
    for (const call of api.calls.filter((c) => c.path === "/query")) {
      expect(Object.keys(JSON.parse(String(call.init?.body)) as object)).toEqual(["question"]);
    }

    // A question asked while history is on screen goes to the current documents' conversation.
    await user.click(screen.getByRole("button", { name: "Back to the current documents" }));
    expect(questions()).toEqual([]);
  });

  it("separates conversations for different explicit document selections", async () => {
    const { api, user } = setup({
      "GET /documents": { body: { documents: [handbook, notes] } },
      "POST /query": { body: answered },
    });
    await ask(user, "All-documents question?");
    await screen.findByRole("region", { name: "Answer" });

    await user.click(screen.getByRole("checkbox", { name: "Limit questions to handbook.pdf" }));
    await waitFor(() => expect(questions()).toEqual([]));
    await ask(user, "Handbook-only question?");
    await waitFor(() => expect(questions()).toEqual(["Question: Handbook-only question?"]));
    expect(JSON.parse(String(api.calls.filter((c) => c.path === "/query").at(-1)?.init?.body))).toEqual({
      question: "Handbook-only question?",
      document_ids: [handbook.document_id],
    });

    // Back to all documents: the first conversation returns with its own turn only.
    await user.click(screen.getByRole("checkbox", { name: "Limit questions to handbook.pdf" }));
    await waitFor(() => expect(questions()).toEqual(["Question: All-documents question?"]));

    // History of the selection can be continued by restoring that selection.
    await openThreadContaining(user, "handbook.pdf (other documents)");
    expect(questions()).toEqual(["Question: Handbook-only question?"]);
    await user.click(screen.getByRole("button", { name: "Use these documents again" }));
    expect(screen.getByRole("checkbox", { name: "Limit questions to handbook.pdf" })).toBeChecked();
    expect(screen.queryByText("Earlier conversation with a different set of documents")).not.toBeInTheDocument();
    expect(questions()).toEqual(["Question: Handbook-only question?"]);
  });

  it("starts a new conversation on request, clears only the one on screen, and keeps all after a reload", async () => {
    const first = setup({ "GET /documents": { body: { documents: [handbook] } }, "POST /query": { body: answered } });
    await ask(first.user, "First?");
    await screen.findByRole("region", { name: "Answer" });

    await first.user.click(screen.getByRole("button", { name: "New conversation" }));
    expect(questions()).toEqual([]);
    await ask(first.user, "Second?");
    await waitFor(() => expect(questions()).toEqual(["Question: Second?"]));
    expect(options()).toHaveLength(2);

    first.view.unmount(); // reload of the tab
    const second = setup({ "GET /documents": { body: { documents: [handbook] } }, "POST /query": { body: answered } });
    await waitFor(() => expect(questions()).toEqual(["Question: Second?"]));
    expect(options()).toHaveLength(2);

    await second.user.click(screen.getByRole("button", { name: "Clear conversation" }));
    expect(screen.getByRole("group", { name: "Confirm clearing the conversation" })).toHaveTextContent("Other conversations are kept");
    await second.user.click(within(screen.getByRole("group", { name: "Confirm clearing the conversation" })).getByRole("button", { name: "Clear" }));
    expect(questions()).toEqual([]);
    expect(options().filter((o) => o.includes("question"))).toHaveLength(1);
    await openThreadContaining(second.user, "1 question");
    expect(questions()).toEqual(["Question: First?"]);
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toContain("First?");
    expect(window.sessionStorage.getItem(STORAGE_KEY)).not.toContain("Second?");
  });

  it("reopens a conversation limited to selected documents after a reload", async () => {
    const first = setup({ "GET /documents": { body: { documents: [handbook, notes] } }, "POST /query": { body: answered } });
    await first.user.click(await screen.findByRole("checkbox", { name: "Limit questions to notes.txt" }));
    await ask(first.user, "Notes only?");
    await screen.findByRole("region", { name: "Answer" });
    first.view.unmount(); // reload of the tab
    setup({ "GET /documents": { body: { documents: [handbook, notes] } } });
    await waitFor(() => expect(questions()).toEqual(["Question: Notes only?"]));
    expect(screen.getByRole("checkbox", { name: "Limit questions to notes.txt" })).toBeChecked();
    expect(screen.getAllByRole("button", { name: /Source S1/ }).length).toBeGreaterThan(0); // citations still open
  });

  it("delivers a pending answer to its own conversation after the document context changed", async () => {
    let release: (r: Response) => void = () => undefined;
    const gate = new Promise<Response>((resolve) => {
      release = resolve;
    });
    const { user } = setup({
      "GET /documents": { body: { documents: [handbook, notes] } },
      "POST /query": [() => gate, { body: belowThreshold }],
    });
    await ask(user, "Slow question?");
    await screen.findByText(/Retrieving evidence/);

    await user.click(screen.getByRole("checkbox", { name: "Limit questions to notes.txt" }));
    await waitFor(() => expect(questions()).toEqual([]));
    await act(async () => release(json(200, answered)));
    await ask(user, "Notes question?");
    await screen.findByRole("region", { name: "Insufficient evidence" });
    expect(questions()).toEqual(["Question: Notes question?"]);
    expect(screen.queryByRole("region", { name: "Answer" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Limit questions to notes.txt" }));
    await waitFor(() => expect(questions()).toEqual(["Question: Slow question?"]));
    expect(screen.getByRole("region", { name: "Answer" })).toHaveTextContent("Employees receive 25 days");
  });

  it("retries a failed turn with its original scope inside its own conversation", async () => {
    const { api, user } = setup({
      "GET /documents": { body: { documents: [handbook, notes] } },
      "POST /query": [{ status: 503, body: { error: { code: "generation_unavailable", message: "Ollama is down." } } }, { body: answered }],
    });
    await user.click(await screen.findByRole("checkbox", { name: "Limit questions to handbook.pdf" }));
    await ask(user, "Scoped question?");
    await screen.findByRole("alert");
    await user.click(screen.getByRole("checkbox", { name: "Limit questions to handbook.pdf" }));
    await openThreadContaining(user, "handbook.pdf (other documents)");
    await user.click(screen.getByRole("button", { name: /Retry/ }));
    await screen.findByRole("region", { name: "Answer" });
    expect(JSON.parse(String(api.calls.filter((c) => c.path === "/query").at(-1)?.init?.body))).toEqual({
      question: "Scoped question?",
      document_ids: [handbook.document_id],
    });
    expect(questions()).toEqual(["Question: Scoped question?"]);
  });

  it("keeps a conversation stored by the previous version as an earlier conversation", async () => {
    const response: QueryResponse = answered;
    window.sessionStorage.setItem(
      LEGACY_STORAGE_KEY,
      JSON.stringify({
        version: 1,
        turns: [{ id: "turn-old", question: "Old SIH question?", scope: null, scopeNames: [], state: { kind: "done", response } }],
        selection: { turnId: null, sourceId: null },
      }),
    );
    const { user } = setup({ "GET /documents": { body: { documents: [agrisense] } }, "POST /query": { body: answered } });
    await screen.findByRole("combobox", { name: /Conversations in this tab/ });
    expect(questions()).toEqual([]); // not presented as belonging to the current documents
    await openThreadContaining(user, "Earlier conversation");
    expect(questions()).toEqual(["Question: Old SIH question?"]);
    await waitFor(() => expect(window.sessionStorage.getItem(STORAGE_KEY)).toContain("Old SIH question?"));
    expect(window.sessionStorage.getItem(LEGACY_STORAGE_KEY)).toBeNull();
  });
});
