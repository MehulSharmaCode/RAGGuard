/**
 * Chooses the 3D scene or the 2D diagram and loads the 3D module lazily.
 * 3D is used only when WebGL works, motion is allowed, the screen is at least
 * `md` wide, and the user has not chosen the 2D view. While the 3D chunk loads,
 * or if it fails, the 2D diagram is shown.
 */

import { Component, lazy, Suspense, useState, type ReactNode } from "react";
import { hasWebGL, readStorage, useMediaQuery, usePrefersReducedMotion, writeStorage } from "../../../lib/browser";
import type { SceneProps } from "./sceneProps";
import { TraceDiagram2D } from "./TraceDiagram2D";

const TraceScene3D = lazy(() => import("./TraceScene3D"));

class SceneBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

const PREF_KEY = "ragguard.trace.view";

export function useSceneMode() {
  const reducedMotion = usePrefersReducedMotion();
  const wide = useMediaQuery("(min-width: 768px)");
  const [prefer2D, setPrefer2DState] = useState(() => readStorage(PREF_KEY) === "2d");
  const webgl = hasWebGL();

  const unavailableReason = !webgl
    ? "3D needs WebGL, which is unavailable here"
    : reducedMotion
      ? "2D because reduced motion is requested"
      : !wide
        ? "2D on small screens"
        : null;

  const setPrefer2D = (value: boolean) => {
    setPrefer2DState(value);
    writeStorage(PREF_KEY, value ? "2d" : null);
  };

  return {
    mode: unavailableReason === null && !prefer2D ? ("3d" as const) : ("2d" as const),
    unavailableReason,
    prefer2D,
    setPrefer2D,
  };
}

export function SceneView({ mode, ...props }: SceneProps & { mode: "3d" | "2d" }) {
  const fallback = <TraceDiagram2D {...props} />;
  if (mode === "2d") return fallback;
  return (
    <SceneBoundary fallback={fallback}>
      <Suspense fallback={fallback}>
        <TraceScene3D {...props} />
      </Suspense>
    </SceneBoundary>
  );
}
