/** Integration tests of the app against a mocked HTTP layer (no live backend, no LLM). */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "../app/App";
import {
  answered,
  belowThreshold,
  handbook,
  HANDBOOK_ID,
  healthDegraded,
  healthOk,
  modelDeclined,
  notes,
} from "./fixtures";
import { mockApi, type Route } from "./mockApi";

function setup(routes: Record<string, Route | Route[]>) {
  const api = mockApi({ "GET /health": { body: healthOk }, ...routes });
  const user = userEvent.setup({ applyAccept: false });
  render(<App />);
  return { api, user };
}

const fileInput = () => screen.getByLabelText("Upload a PDF or TXT document") as HTMLInputElement;

async function ask(user: ReturnType<typeof userEvent.setup>, question: string) {
  const box = await screen.findByRole("textbox", { name: "Question" });
  await waitFor(() => expect(box).toBeEnabled());
  await user.type(box, `${question}{Enter}`);
}

describe("shell and status", () => {
  it("renders the shell with real backend status and honest planned views", async () => {
    const { user } = setup({ "GET /documents": { body: { documents: [] } } });
    expect(screen.getByRole("heading", { level: 1, name: "Document workspace" })).toBeInTheDocument();
    expect(await screen.findByText("Backend connected")).toBeInTheDocument();
    expect(screen.getByText("collection ragguard_chunks")).toBeInTheDocument();

    const nav = screen.getAllByRole("navigation", { name: "Primary" })[0]!;
    await user.click(within(nav).getByRole("link", { name: "Evaluation (planned, stage 4)" }));
    expect(await screen.findByText(/No evaluation runs yet/)).toBeInTheDocument();
    expect(screen.getByText("Planned · Stage 4")).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument(); // no invented metrics
  });

  it("shows an unreachable backend honestly and disables uploads and questions", async () => {
    setup({ "GET /health": "network-error", "GET /documents": "network-error" });
    expect(await screen.findByText("Backend unreachable")).toBeInTheDocument();
    expect(await screen.findByText("The backend is unreachable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose file" })).toBeDisabled();
    expect(screen.getByText("Uploads are unavailable while the backend is unreachable.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Question" })).toBeDisabled();
    expect(screen.getByText("Could not load the document list")).toBeInTheDocument();
  });

  it("warns when generation is unavailable but the API is up", async () => {
    setup({ "GET /health": { body: healthDegraded }, "GET /documents": { body: { documents: [handbook] } } });
    expect(await screen.findByText("Generation unavailable")).toBeInTheDocument();
    expect(screen.getByText("Answer generation is unavailable")).toBeInTheDocument();
    expect(screen.getByText(/The Ollama service is not reachable\./)).toBeInTheDocument();
  });
});

describe("documents", () => {
  it("shows a loading state, then the first-run empty state", async () => {
    setup({ "GET /documents": ["pending"] });
    expect(screen.getByText("Loading documents")).toBeInTheDocument();
  });

  it("shows the empty first-run workspace with the illustration", async () => {
    setup({ "GET /documents": { body: { documents: [] } } });
    expect(await screen.findByRole("heading", { name: "No documents indexed" })).toBeInTheDocument();
    expect(screen.getByText("No documents indexed yet.")).toBeInTheDocument();
    expect(screen.getByText(/Illustration of what happens to an uploaded file/)).toBeInTheDocument();
    expect(screen.getByTestId("trace-2d")).toBeInTheDocument(); // no WebGL in jsdom → 2D fallback
    expect(screen.getByRole("textbox", { name: "Question" })).toBeDisabled();
    expect(await screen.findByText(/up to 1 MB/)).toBeInTheDocument(); // limit from /health config
  });

  it("uploads a file and refreshes the server-side list", async () => {
    const indexed = { ...handbook, pages_with_text: 3 };
    const { api, user } = setup({
      "GET /documents": [{ body: { documents: [] } }, { body: { documents: [handbook] } }],
      "POST /ingest": { status: 201, body: indexed },
    });
    await screen.findByText("No documents indexed yet.");
    await user.upload(fileInput(), new File(["%PDF-1.4 test"], "handbook.pdf", { type: "application/pdf" }));

    expect(await screen.findByText("3 chunks")).toBeInTheDocument();
    expect(screen.getByText(/Indexed ·/)).toBeInTheDocument();
    const body = api.bodyOf("POST /ingest");
    expect(body).toBeInstanceOf(FormData);
    expect(((body as FormData).get("file") as File).name).toBe("handbook.pdf");
    const list = await screen.findByRole("list", { name: "Indexed documents" });
    expect(within(list).getByText("handbook.pdf")).toBeInTheDocument();
    expect(api.count("GET /documents")).toBe(2);
  });

  it("shows the backend's reason when ingestion is rejected", async () => {
    const { user } = setup({
      "GET /documents": { body: { documents: [] } },
      "POST /ingest": {
        status: 422,
        body: { error: { code: "empty_document", message: "No extractable text was found. Scanned or image-only PDFs are not supported." } },
      },
    });
    await screen.findByText("No documents indexed yet.");
    await user.upload(fileInput(), new File(["%PDF-1.4"], "scan.pdf", { type: "application/pdf" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("scan.pdf was not indexed");
    expect(alert).toHaveTextContent("Scanned or image-only PDFs are not supported.");
    expect(alert).toHaveTextContent("empty_document");
    expect(screen.queryByText(/Indexed ·/)).not.toBeInTheDocument();
  });

  it("rejects unsupported, empty, and oversized files before sending them", async () => {
    const { api, user } = setup({ "GET /documents": { body: { documents: [] } } });
    await screen.findByText(/up to 1 MB/);
    await user.upload(fileInput(), new File(["x"], "notes.docx"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Only PDF (.pdf) and plain-text (.txt) files are supported.");
    await user.upload(fileInput(), new File([], "empty.txt", { type: "text/plain" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The file is empty.");
    await user.upload(fileInput(), new File([new Uint8Array(2 * 1024 * 1024)], "big.txt", { type: "text/plain" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("the limit is 1 MB");
    expect(api.count("POST /ingest")).toBe(0);
  });

  it("reports a server error during upload", async () => {
    const { user } = setup({ "GET /documents": { body: { documents: [] } }, "POST /ingest": "network-error" });
    await screen.findByText("No documents indexed yet.");
    await user.upload(fileInput(), new File(["hello"], "notes.txt", { type: "text/plain" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Cannot reach the RAGGuard API/);
  });

  it("recovers from a failed list request via Retry", async () => {
    const { user } = setup({ "GET /documents": ["network-error", { body: { documents: [handbook] } }] });
    expect(await screen.findByText("Could not load the document list")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Retry" })[0]!);
    expect(await screen.findByRole("list", { name: "Indexed documents" })).toHaveTextContent("handbook.pdf");
  });

  it("confirms before deleting, then refreshes the list from the server", async () => {
    const { api, user } = setup({
      "GET /documents": [{ body: { documents: [handbook, notes] } }, { body: { documents: [notes] } }],
      [`DELETE /documents/${HANDBOOK_ID}`]: { body: { document_id: HANDBOOK_ID, deleted_chunks: 3, status: "deleted" } },
    });
    await user.click(await screen.findByRole("button", { name: "Remove handbook.pdf" }));
    const confirm = screen.getByRole("group", { name: "Confirm removal of handbook.pdf" });
    expect(confirm).toHaveTextContent("3 chunks");
    expect(api.count(`DELETE /documents/${HANDBOOK_ID}`)).toBe(0);
    await user.click(within(confirm).getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(screen.queryByText("handbook.pdf")).not.toBeInTheDocument());
    expect(api.count(`DELETE /documents/${HANDBOOK_ID}`)).toBe(1);
    expect(api.count("GET /documents")).toBe(2);
    expect(screen.getByText("notes.txt")).toBeInTheDocument();
  });

  it("keeps the document and shows the error when deletion fails", async () => {
    const { user } = setup({
      "GET /documents": { body: { documents: [handbook] } },
      [`DELETE /documents/${HANDBOOK_ID}`]: { status: 404, body: { error: { code: "document_not_found", message: "No indexed document has this ID." } } },
    });
    await user.click(await screen.findByRole("button", { name: "Remove handbook.pdf" }));
    await user.click(within(screen.getByRole("group", { name: /Confirm removal/ })).getByRole("button", { name: "Remove" }));
    expect(await screen.findByText("No indexed document has this ID.")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Indexed documents" })).toHaveTextContent("handbook.pdf");
  });
});

describe("questions and evidence", () => {
  const withDocs = { "GET /documents": { body: { documents: [handbook, notes] } } };

  it("renders an answer with genuine sources and inspectable evidence", async () => {
    const { api, user } = setup({ ...withDocs, "POST /query": { body: answered } });
    await ask(user, "How much annual leave do employees get?");

    const answer = await screen.findByRole("region", { name: "Answer" });
    expect(answer).toHaveTextContent("Employees receive 25 days of paid annual leave");
    expect(within(answer).getByText("Interpretation")).toBeInTheDocument();
    expect(answer).toHaveTextContent("embedding 43 ms · retrieval <1 ms · generation 811 ms · total 855 ms");
    expect(answer).toHaveTextContent("qwen3.5:9b via ollama");
    expect(JSON.parse(String(api.bodyOf("POST /query")))).toEqual({ question: "How much annual leave do employees get?" });

    const citations = within(answer).getAllByRole("button", { name: "Source S1: handbook.pdf, p. 2" });
    expect(citations).toHaveLength(2);
    await user.click(citations[0]!);

    const evidence = screen.getByRole("list", { name: "Evidence passages" });
    const items = within(evidence).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("handbook.pdf");
    expect(items[0]).toHaveTextContent("p. 2 · chunk 1 · score 0.877");
    expect(items[0]).toHaveTextContent("Cited in the answer");
    expect(items[0]).toHaveTextContent("Employees receive 25 days of paid annual leave per calendar year.");
    expect(within(items[0]!).getByRole("button", { pressed: true })).toBeInTheDocument();
    expect(items[1]).toHaveTextContent("notes.txt");
    expect(items[1]).toHaveTextContent("no page number · chunk 0 · score 0.401");
    expect(items[1]).toHaveTextContent("Supplied to the model, not cited");
  });

  it("limits a question to the selected documents", async () => {
    const { api, user } = setup({ ...withDocs, "POST /query": { body: answered } });
    await user.click(await screen.findByRole("checkbox", { name: "Limit questions to handbook.pdf" }));
    expect(screen.getByText("1 selected document")).toBeInTheDocument();
    await ask(user, "Leave?");
    await screen.findByRole("region", { name: "Answer" });
    expect(JSON.parse(String(api.bodyOf("POST /query")))).toEqual({ question: "Leave?", document_ids: [HANDBOOK_ID] });
    expect(screen.getByText("Limited to handbook.pdf")).toBeInTheDocument();
  });

  it("shows the insufficient-evidence fallback as distinct from an answer", async () => {
    const { user } = setup({ ...withDocs, "POST /query": { body: belowThreshold } });
    await ask(user, "What is the dress code?");
    const fallback = await screen.findByRole("region", { name: "Insufficient evidence" });
    expect(fallback).toHaveTextContent("Not enough evidence to answer");
    expect(fallback).toHaveTextContent("did not provide sufficient evidence");
    expect(fallback).toHaveTextContent("4 passages retrieved; the closest scored 0.313, below the 0.350 evidence threshold. The model was not called.");
    expect(screen.queryByRole("region", { name: "Answer" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Trace this answer" })).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(); // a fallback is not an error
  });

  it("explains a fallback where the model declined", async () => {
    const { user } = setup({ ...withDocs, "POST /query": { body: modelDeclined } });
    await ask(user, "What is the population?");
    expect(await screen.findByRole("region", { name: "Insufficient evidence" })).toHaveTextContent(
      "1 passage passed the 0.350 similarity threshold, but the model (qwen3.5:9b) judged that they do not answer the question.",
    );
  });

  it("shows a failed request as an error with retry, not as a fallback", async () => {
    const { user } = setup({
      ...withDocs,
      "POST /query": [
        { status: 503, body: { error: { code: "generation_unavailable", message: "The Ollama service is not reachable. Start it with `ollama serve` and check OLLAMA_BASE_URL." } } },
        { body: answered },
      ],
    });
    await ask(user, "Leave?");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Request failed — no answer was produced");
    expect(alert).toHaveTextContent("The Ollama service is not reachable.");
    expect(alert).toHaveTextContent("generation_unavailable");
    expect(screen.queryByText("Not enough evidence to answer")).not.toBeInTheDocument();
    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("region", { name: "Answer" })).toBeInTheDocument();
  });

  it("shows a validation error from the API", async () => {
    const { user } = setup({
      ...withDocs,
      "POST /query": { status: 422, body: { error: { code: "validation_error", message: "The request is invalid.", details: [] } } },
    });
    await ask(user, "x");
    expect(await screen.findByRole("alert")).toHaveTextContent("The request is invalid.");
  });
});

describe("Evidence Trace", () => {
  const routes = {
    "GET /documents": { body: { documents: [handbook, notes] } },
    "POST /query": { body: answered },
  };

  it("traces a real answer with a keyboard-operable stepper and evidence selection", async () => {
    const { user } = setup(routes);
    await ask(user, "Leave?");
    await user.click(await screen.findByRole("button", { name: "Trace this answer" }));

    const trace = screen.getByRole("region", { name: "Evidence trace" });
    expect(within(trace).getByTestId("trace-2d")).toBeInTheDocument(); // jsdom has no WebGL
    expect(within(trace).getByText("3D needs WebGL, which is unavailable here")).toBeInTheDocument();

    const tabs = within(trace).getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual([
      "1 Documents2 documents",
      "2 Chunks2 highlighted",
      "3 Evidence2 supplied",
      "4 Answercites 1",
    ]);
    expect(tabs[2]).toHaveAttribute("aria-selected", "true");

    const nodes = within(trace).getByRole("list", { name: "Evidence nodes" });
    await user.click(within(nodes).getByRole("button", { name: /S2/ }));
    expect(within(nodes).getByRole("button", { name: /S2/ })).toHaveAttribute("aria-pressed", "true");
    const evidenceItems = within(screen.getByRole("list", { name: "Evidence passages" })).getAllByRole("listitem");
    expect(within(evidenceItems[1]!).getByRole("button", { pressed: true })).toHaveTextContent("notes.txt");

    tabs[2]!.focus();
    await user.keyboard("{ArrowRight}");
    expect(within(trace).getByRole("tab", { selected: true })).toHaveTextContent("Answer");
    expect(within(trace).getByRole("tabpanel")).toHaveTextContent("The answer cites S1; only those are linked to the answer.");
    await user.keyboard("{Home}");
    expect(within(trace).getByRole("tab", { selected: true })).toHaveTextContent("Documents");
    expect(within(trace).getByRole("tabpanel")).toHaveTextContent("handbook.pdf PDF · 3 pages");
    expect(within(trace).getByRole("tabpanel")).toHaveTextContent("Evidence from p. 2");
    expect(within(trace).getByRole("tabpanel")).toHaveTextContent("Evidence from a file without page numbers");
    await user.keyboard("{End}{ArrowRight}");
    expect(within(trace).getByRole("tab", { selected: true })).toHaveTextContent("Documents");
    expect(trace).toHaveTextContent("it does not prove the answer is correct");
  });

  it("says so when a traced document is no longer listed", async () => {
    const { user } = setup({
      "GET /documents": [{ body: { documents: [handbook, notes] } }, { body: { documents: [notes] } }],
      "POST /query": { body: answered },
      [`DELETE /documents/${HANDBOOK_ID}`]: { body: { document_id: HANDBOOK_ID, deleted_chunks: 3, status: "deleted" } },
    });
    await ask(user, "Leave?");
    await user.click(await screen.findByRole("button", { name: "Trace this answer" }));
    await user.click(screen.getByRole("button", { name: "Remove handbook.pdf" }));
    await user.click(within(screen.getByRole("group", { name: /Confirm removal/ })).getByRole("button", { name: "Remove" }));
    const trace = screen.getByRole("region", { name: "Evidence trace" });
    await user.click(within(trace).getByRole("tab", { name: /Documents/ }));
    await waitFor(() =>
      expect(within(trace).getByRole("tabpanel")).toHaveTextContent("no longer in the document list; totals unknown"),
    );
  });

});
