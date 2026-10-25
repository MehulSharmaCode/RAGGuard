import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom has no WebGL: report "unsupported" quietly so the 2D fallback is used.
HTMLCanvasElement.prototype.getContext = (() => null) as typeof HTMLCanvasElement.prototype.getContext;

afterEach(() => {
  cleanup();
  window.localStorage.clear();
  window.sessionStorage.clear(); // the conversation is kept per tab in sessionStorage
  window.location.hash = "";
});
