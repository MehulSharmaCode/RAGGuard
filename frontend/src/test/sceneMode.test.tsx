/**
 * Renderer selection for the Evidence Trace. This file simulates a browser that
 * reports WebGL support (set before the first detection, which is cached per
 * module instance) and controls media queries.
 */

import { render, screen } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { EvidenceTrace } from "../features/chat/trace/EvidenceTrace";
import { answered, handbook, notes } from "./fixtures";

// jsdom cannot run three.js, so the lazily loaded 3D module is replaced by a stand-in
// that either renders a marker or throws, to exercise both paths of SceneView.
const scene = vi.hoisted(() => ({ fail: false, renders: 0 }));
vi.mock("../features/chat/trace/TraceScene3D", () => ({
  default: () => {
    scene.renders += 1;
    if (scene.fail) throw new Error("WebGL renderer could not be created");
    return <div data-testid="trace-3d" />;
  },
}));

beforeAll(() => {
  // Report WebGL as available (detection is cached per module instance).
  HTMLCanvasElement.prototype.getContext = (() => ({})) as unknown as typeof HTMLCanvasElement.prototype.getContext;
});

function mockMedia(matches: Record<string, boolean>) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: matches[query] ?? false,
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

const renderTrace = () =>
  render(
    <EvidenceTrace response={answered} documents={[handbook, notes]} selectedSourceId={null} onSelectSource={() => undefined} />,
  );

describe("Evidence Trace renderer selection", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("uses the 2D diagram when reduced motion is requested", () => {
    mockMedia({ "(prefers-reduced-motion: reduce)": true, "(min-width: 768px)": true });
    renderTrace();
    expect(screen.getByText("2D because reduced motion is requested")).toBeInTheDocument();
    expect(screen.getByTestId("trace-2d")).toBeInTheDocument();
    expect(screen.queryByTestId("trace-3d")).not.toBeInTheDocument();
  });

  it("uses the 2D diagram on small screens", () => {
    mockMedia({ "(min-width: 768px)": false });
    renderTrace();
    expect(screen.getByText("2D on small screens")).toBeInTheDocument();
    expect(screen.getByTestId("trace-2d")).toBeInTheDocument();
  });

  it("renders the 3D scene when WebGL, motion, and screen size allow it", async () => {
    mockMedia({ "(min-width: 768px)": true });
    scene.fail = false;
    renderTrace();
    expect(screen.getByRole("button", { name: "Show 2D view" })).toBeInTheDocument();
    expect(await screen.findByTestId("trace-3d")).toBeInTheDocument();
    expect(screen.queryByTestId("trace-2d")).not.toBeInTheDocument();
  });

  it("falls back to the 2D diagram when the 3D scene fails", async () => {
    mockMedia({ "(min-width: 768px)": true });
    scene.fail = true;
    scene.renders = 0;
    vi.spyOn(console, "error").mockImplementation(() => undefined); // React logs the caught error
    renderTrace();
    await vi.waitFor(() => expect(scene.renders).toBeGreaterThan(0));
    expect(await screen.findByTestId("trace-2d")).toBeInTheDocument();
    expect(screen.queryByTestId("trace-3d")).not.toBeInTheDocument();
  });
});
