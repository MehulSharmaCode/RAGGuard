/** Small browser helpers: media queries, safe storage, WebGL detection, theme. */

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (typeof window.matchMedia !== "function") return () => undefined;
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    [query],
  );
  return useSyncExternalStore(
    subscribe,
    () => typeof window.matchMedia === "function" && window.matchMedia(query).matches,
    () => false,
  );
}

export const usePrefersReducedMotion = () => useMediaQuery("(prefers-reduced-motion: reduce)");

export function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStorage(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // Storage unavailable (private mode, blocked): preferences simply are not remembered.
  }
}

let webglSupport: boolean | null = null;

export function hasWebGL(): boolean {
  if (webglSupport !== null) return webglSupport;
  try {
    const canvas = document.createElement("canvas");
    webglSupport = Boolean(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch {
    webglSupport = false;
  }
  return webglSupport;
}

export type ThemeChoice = "system" | "light" | "dark";
const THEME_KEY = "ragguard.theme";

function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
}

export function useTheme(): [ThemeChoice, (choice: ThemeChoice) => void] {
  const [choice, setChoice] = useState<ThemeChoice>(() => {
    const stored = readStorage(THEME_KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  });
  useEffect(() => {
    applyTheme(choice);
    writeStorage(THEME_KEY, choice === "system" ? null : choice);
  }, [choice]);
  return [choice, setChoice];
}

/** Resolved token values, for code (the 3D scene) that cannot use CSS variables directly. */
export function readTokens<K extends string>(names: readonly K[]): Record<K, string> {
  const style = getComputedStyle(document.documentElement);
  return Object.fromEntries(
    names.map((name) => [name, style.getPropertyValue(`--${name}`).trim() || "#888888"]),
  ) as Record<K, string>;
}
