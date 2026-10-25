import { useEffect, useState } from "react";

export type View = "workspace" | "evaluation" | "experiments" | "pipeline";
const VIEWS: readonly View[] = ["workspace", "evaluation", "experiments", "pipeline"];

export interface Route {
  view: View;
  /** Optional item inside the view, e.g. `#/evaluation/<run_id>` selects a report. */
  param: string | null;
}

function read(): Route {
  const [name = "", ...rest] = window.location.hash.replace(/^#\/?/, "").split("/");
  if (!(VIEWS as readonly string[]).includes(name)) return { view: "workspace", param: null };
  let param: string | null;
  try {
    param = rest.length ? decodeURIComponent(rest.join("/")) || null : null;
  } catch {
    param = null; // malformed escape sequence: ignore the parameter
  }
  return { view: name as View, param };
}

/** Minimal hash routing for four top-level views (no router dependency needed). */
export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(read);
  useEffect(() => {
    const onChange = () => setRoute(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}

export function routeHref(view: View, param?: string | null): string {
  return param ? `#/${view}/${encodeURIComponent(param)}` : `#/${view}`;
}
