/**
 * Test-only HTTP mock. Routes are keyed "METHOD /path". A route can be a
 * response spec, "network-error", "pending" (never settles), a function, or an
 * array consumed in order (the last entry repeats).
 */

import { vi } from "vitest";

type Spec = { status?: number; body?: unknown };
type Handler = (init: RequestInit | undefined) => Response | Promise<Response>;
export type Route = Spec | "network-error" | "pending" | Handler;

export interface Call {
  method: string;
  path: string;
  /** Query string including "?", or "" (routes are matched on the path only). */
  search: string;
  init: RequestInit | undefined;
}

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export function mockApi(routes: Record<string, Route | Route[]>) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    const key = `${method} ${url.pathname}`;
    calls.push({ method, path: url.pathname, search: url.search, init });
    const entry = routes[key];
    const route = Array.isArray(entry) ? (entry.length > 1 ? entry.shift() : entry[0]) : entry;
    if (route === undefined) throw new Error(`Unmocked request: ${key}`);
    if (route === "network-error") throw new TypeError("Failed to fetch");
    if (route === "pending") return new Promise<Response>(() => undefined);
    if (typeof route === "function") return route(init);
    return json(route.status ?? 200, route.body);
  });
  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    count: (key: string) => calls.filter((c) => `${c.method} ${c.path}` === key).length,
    bodyOf: (key: string) => {
      const call = calls.filter((c) => `${c.method} ${c.path}` === key).at(-1);
      return call?.init?.body;
    },
  };
}
