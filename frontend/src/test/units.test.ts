/** Unit tests: API client, answer parsing, trace model/layout, design-token contrast. */

import { describe, expect, it, vi } from "vitest";
import { ApiError, request } from "../lib/api/client";
import { isQueryResponse } from "../lib/api/guards";
import { parseAnswer } from "../features/chat/parseAnswer";
import { toSceneInput } from "../features/chat/trace/EvidenceTrace";
import { computeLayout } from "../features/chat/trace/layout";
import { buildTraceModel } from "../features/chat/trace/traceModel";
import tokensCss from "../styles/tokens.css?raw";
import { answered, handbook, HANDBOOK_ID, notes } from "./fixtures";
import { mockApi } from "./mockApi";

const anything = (v: unknown): v is unknown => v !== undefined;

describe("API client", () => {
  it("returns validated JSON", async () => {
    mockApi({ "POST /query": { body: answered } });
    await expect(request("/query", { method: "POST", json: {}, timeoutMs: 1000 }, isQueryResponse)).resolves.toEqual(answered);
  });

  it("surfaces the backend error code and message", async () => {
    mockApi({
      "POST /ingest": { status: 415, body: { error: { code: "unsupported_file", message: "Only .pdf and .txt files are supported." } } },
    });
    const error = await request("/ingest", { method: "POST", timeoutMs: 1000 }, anything).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ kind: "http", status: 415, code: "unsupported_file", message: "Only .pdf and .txt files are supported." });
  });

  it("handles non-JSON error bodies", async () => {
    mockApi({ "GET /health": () => new Response("<html>Bad gateway</html>", { status: 502 }) });
    await expect(request("/health", { timeoutMs: 1000 }, anything)).rejects.toMatchObject({
      kind: "http",
      status: 502,
      message: "The server returned HTTP 502.",
    });
  });

  it("reports network failures", async () => {
    mockApi({ "GET /health": "network-error" });
    await expect(request("/health", { timeoutMs: 1000 }, anything)).rejects.toMatchObject({ kind: "network" });
  });

  it("reports malformed responses instead of passing them on", async () => {
    mockApi({ "POST /query": { body: { answer: "x" } } });
    await expect(request("/query", { method: "POST", timeoutMs: 1000 }, isQueryResponse)).rejects.toMatchObject({
      kind: "malformed",
    });
  });

  it("times out", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init: RequestInit) =>
          new Promise((_resolve, reject) =>
            init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError"))),
          ),
      ),
    );
    await expect(request("/query", { timeoutMs: 20 }, anything)).rejects.toMatchObject({ kind: "timeout" });
  });
});

describe("parseAnswer", () => {
  const ids = new Set(["S1", "S2"]);

  it("links only source IDs present in the response", () => {
    const [block] = parseAnswer("Fact A [S1]. Fact B [S9].", ids);
    expect(block).toEqual({
      type: "paragraph",
      interpretation: false,
      segments: [
        { type: "text", text: "Fact A " },
        { type: "cite", sourceId: "S1" },
        { type: "text", text: ". Fact B [S9]." },
      ],
    });
  });

  it("separates interpretation sentences and parses lists", () => {
    const blocks = parseAnswer("Stated [S1]. Interpretation: a reading.\n\n- one [S2]\n- **two**\n\n1. first\n2. second", ids);
    expect(blocks.map((b) => b.type)).toEqual(["paragraph", "paragraph", "list", "list"]);
    expect(blocks[1]).toMatchObject({ interpretation: true, segments: [{ type: "text", text: "a reading." }] });
    expect(blocks[2]).toMatchObject({ ordered: false, items: [[{ type: "text", text: "one " }, { type: "cite", sourceId: "S2" }], [{ type: "strong", text: "two" }]] });
    expect(blocks[3]).toMatchObject({ ordered: true });
  });
});

describe("Evidence Trace model", () => {
  it("uses real listing totals when the document is listed", () => {
    const model = buildTraceModel(answered, [handbook, notes]);
    expect(model.documents).toHaveLength(2);
    expect(model.documents[0]).toMatchObject({ filename: "handbook.pdf", listed: true, totalPages: 3, chunkCount: 3 });
    expect(model.documents[1]).toMatchObject({ filename: "notes.txt", listed: true, totalPages: null, chunkCount: 1 });
    expect(model.citedCount).toBe(1);
    expect(model.evidence.map((e) => [e.sourceId, e.cited, e.pageNumber])).toEqual([
      ["S1", true, 2],
      ["S2", false, null],
    ]);
  });

  it("leaves totals unknown when the document is no longer listed", () => {
    const model = buildTraceModel(answered, []);
    expect(model.documents[0]).toMatchObject({ listed: false, totalPages: null, chunkCount: null, fileType: null });
  });

  it("lays out real pages and chunks and links only cited evidence to the answer", () => {
    const layout = computeLayout(toSceneInput(buildTraceModel(answered, [handbook, notes])));
    const handbookTiles = layout.pages.filter((p) => p.documentIndex === 0);
    expect(handbookTiles).toHaveLength(3); // real page count
    expect(handbookTiles.map((t) => t.keys)).toEqual([[], ["S1"], []]); // page 2 highlighted
    const handbookStrips = layout.strips.filter((s) => s.documentIndex === 0);
    expect(handbookStrips).toHaveLength(3); // real chunk count
    expect(handbookStrips.map((s) => s.keys)).toEqual([[], ["S1"], []]); // chunk_index 1
    expect(layout.nodes.map((n) => [n.key, n.cited])).toEqual([["S1", true], ["S2", false]]);
    const toAnswer = layout.links.filter((l) => l.kind === "evidence-answer").map((l) => l.key);
    expect(toAnswer).toEqual(["S1"]);
    const scoreLink = layout.links.find((l) => l.kind === "chunk-evidence" && l.key === "S2");
    expect(scoreLink?.strength).toBeCloseTo(0.4012); // link strength is the real score
  });

  it("draws only retrieved chunks when totals are unknown", () => {
    const layout = computeLayout(toSceneInput(buildTraceModel(answered, null)));
    expect(layout.strips.filter((s) => s.documentIndex === 0)).toHaveLength(1);
    expect(layout.pages.filter((p) => p.documentIndex === 0)).toHaveLength(1);
    expect(layout.scale.every((s) => !s.pagesScaled && !s.chunksScaled)).toBe(true);
  });

  it("scales large documents and reports it", () => {
    const big = { ...handbook, total_pages: 400, chunk_count: 900 };
    const response = { ...answered, sources: [{ ...answered.sources[0]!, page_number: 400, chunk_index: 899 }] };
    const layout = computeLayout(toSceneInput(buildTraceModel(response, [big])));
    expect(layout.scale[0]).toMatchObject({ pagesScaled: true, chunksScaled: true });
    const tiles = layout.pages.filter((p) => p.documentIndex === 0);
    expect(tiles.at(-1)?.keys).toEqual(["S1"]); // last page maps to the last tile
    expect(layout.strips.at(-1)?.keys).toEqual(["S1"]);
    expect(response.sources[0]?.document_id).toBe(HANDBOOK_ID);
  });
});

describe("design tokens", () => {
  function block(selector: string): Record<string, string> {
    const start = tokensCss.indexOf(`${selector} {`);
    const body = tokensCss.slice(start, tokensCss.indexOf("}", start));
    return Object.fromEntries([...body.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1]!, m[2]!]));
  }
  function luminance(hex: string): number {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
    const f = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
    return 0.2126 * f(r!) + 0.7152 * f(g!) + 0.0722 * f(b!);
  }
  function ratio(a: string, b: string): number {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi! + 0.05) / (lo! + 0.05);
  }

  const light = block(":root");
  const dark = { ...light, ...block(':root[data-theme="dark"]') };

  it.each([
    ["light", light],
    ["dark", dark],
  ])("meets WCAG AA in the %s theme", (_name, t) => {
    const surfaces = ["paper-50", "paper-100", "paper-200"];
    for (const text of ["ink-900", "ink-700", "ink-500", "accent-800", "status-pass", "status-fail", "status-warn"]) {
      for (const surface of surfaces) expect(ratio(t[text]!, t[surface]!), `${text} on ${surface}`).toBeGreaterThanOrEqual(4.5);
    }
    for (const surface of surfaces) expect(ratio(t["line-strong"]!, t[surface]!), `line-strong on ${surface}`).toBeGreaterThanOrEqual(3);
    expect(ratio(t["on-accent"]!, t["accent-300"]!)).toBeGreaterThanOrEqual(4.5);
    expect(ratio(t["on-accent"]!, t["accent-500"]!)).toBeGreaterThanOrEqual(4.5);
    expect(ratio(t["paper-50"]!, t["ink-900"]!)).toBeGreaterThanOrEqual(4.5); // primary button
    expect(ratio(t["paper-50"]!, t["status-fail"]!)).toBeGreaterThanOrEqual(4.5); // destructive button
    expect(ratio(t["ink-900"]!, t["paper-100"]!)).toBeGreaterThanOrEqual(3); // focus ring inner edge
  });

  it("keeps the system-dark block identical to the explicit dark theme", () => {
    const media = tokensCss.slice(tokensCss.indexOf("@media (prefers-color-scheme: dark)"));
    const explicit = block(':root[data-theme="dark"]');
    for (const [name, value] of Object.entries(explicit)) expect(media).toContain(`--${name}: ${value}`);
  });
});
