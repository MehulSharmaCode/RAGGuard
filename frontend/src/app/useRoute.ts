import { useEffect, useState } from "react";

export type View = "workspace" | "evaluation" | "experiments" | "pipeline";
const VIEWS: readonly View[] = ["workspace", "evaluation", "experiments", "pipeline"];

function read(): View {
  const name = window.location.hash.replace(/^#\/?/, "");
  return (VIEWS as readonly string[]).includes(name) ? (name as View) : "workspace";
}

/** Minimal hash routing for four top-level views (no router dependency needed). */
export function useRoute(): View {
  const [view, setView] = useState<View>(read);
  useEffect(() => {
    const onChange = () => setView(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return view;
}
