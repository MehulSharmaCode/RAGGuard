/**
 * 3D rendering of the Evidence Trace layout (Three.js via React Three Fiber).
 * Loaded lazily; procedural geometry only; renders on demand (no animation loop).
 * The canvas is decorative for assistive technology (aria-hidden); the stage panel
 * next to it carries the same information as text.
 */

import { Canvas, useThree, type ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import { BufferGeometry, Color, Float32BufferAttribute, LineBasicMaterial, LineSegments, type OrthographicCamera } from "three";
import { readTokens, useMediaQuery } from "../../../lib/browser";
import { VIEW, type Link } from "./layout";
import { DIM, type SceneProps } from "./sceneProps";

const TOKENS = [
  "ink-900",
  "ink-500",
  "ink-300",
  "paper-50",
  "paper-200",
  "paper-300",
  "accent-300",
  "accent-500",
  "line-strong",
] as const;
type Palette = Record<(typeof TOKENS)[number], string>;

function FitCamera() {
  const camera = useThree((s) => s.camera) as OrthographicCamera;
  const size = useThree((s) => s.size);
  const invalidate = useThree((s) => s.invalidate);
  useEffect(() => {
    // three.js cameras are mutable objects by design; R3F expects them to be updated in place.
    // eslint-disable-next-line react-hooks/immutability
    camera.zoom = Math.min(size.width / VIEW.width, size.height / VIEW.height) * 0.95;
    camera.updateProjectionMatrix();
    invalidate();
  }, [camera, size, invalidate]);
  return null;
}

/** All links in one draw call; per-link strength is mixed toward the background colour. */
function Links({ links, palette, selectedKey, activeStage }: {
  links: Link[];
  palette: Palette;
  selectedKey: string | null;
  activeStage: number | null;
}) {
  const object = useMemo(() => {
    const background = new Color(palette["paper-50"]);
    const positions: number[] = [];
    const colors: number[] = [];
    for (const link of links) {
      const selected = link.key === selectedKey;
      const base = new Color(
        selected ? palette["ink-900"] : link.kind === "evidence-answer" ? palette["accent-500"] : palette["ink-500"],
      );
      const dim = activeStage === null || activeStage === link.station ? 1 : DIM;
      const color = background.clone().lerp(base, (selected ? 1 : link.strength) * dim);
      const z = link.kind === "chunk-evidence" ? 0.12 : 0.02;
      positions.push(link.from[0], link.from[1], z, link.to[0], link.to[1], z);
      colors.push(color.r, color.g, color.b, color.r, color.g, color.b);
    }
    const geometry = new BufferGeometry();
    geometry.setAttribute("position", new Float32BufferAttribute(positions, 3));
    geometry.setAttribute("color", new Float32BufferAttribute(colors, 3));
    return new LineSegments(geometry, new LineBasicMaterial({ vertexColors: true }));
  }, [links, palette, selectedKey, activeStage]);

  useEffect(
    () => () => {
      object.geometry.dispose();
      (object.material as LineBasicMaterial).dispose();
    },
    [object],
  );
  return <primitive object={object} />;
}

function Slab({ x, y, z = 0, w, h, d, color, opacity = 1, onClick }: {
  x: number;
  y: number;
  z?: number;
  w: number;
  h: number;
  d: number;
  color: string;
  opacity?: number;
  onClick?: (e: ThreeEvent<MouseEvent>) => void;
}) {
  return (
    <mesh
      position={[x, y, z]}
      onClick={onClick}
      onPointerOver={onClick ? () => (document.body.style.cursor = "pointer") : undefined}
      onPointerOut={onClick ? () => (document.body.style.cursor = "") : undefined}
    >
      <boxGeometry args={[w, h, d]} />
      <meshStandardMaterial color={color} roughness={0.95} metalness={0} transparent={opacity < 1} opacity={opacity} />
    </mesh>
  );
}

export default function TraceScene3D({ layout, selectedKey, activeStage, onSelect }: SceneProps) {
  // Re-read token colours when the colour scheme changes.
  const dark = useMediaQuery("(prefers-color-scheme: dark)");
  const theme = typeof document !== "undefined" ? document.documentElement.dataset.theme : undefined;
  const palette = useMemo(() => readTokens(TOKENS), [dark, theme]); // eslint-disable-line react-hooks/exhaustive-deps
  const op = (station: number) => (activeStage === null || activeStage === station ? 1 : DIM);
  const hit = (keys: string[]) => selectedKey !== null && keys.includes(selectedKey);

  useEffect(() => () => void (document.body.style.cursor = ""), []);

  return (
    <div className="h-full w-full" aria-hidden="true" data-testid="trace-3d">
      <Canvas
        orthographic
        frameloop="demand"
        dpr={[1, 1.5]}
        camera={{ position: [0, 0, 20], near: 0.1, far: 100 }}
        gl={{ antialias: true, alpha: true, powerPreference: "low-power" }}
      >
        <FitCamera />
        <ambientLight intensity={1.6} />
        <directionalLight position={[-4, 6, 10]} intensity={1.4} />
        <group rotation={[0.1, -0.3, 0]}>
          {layout.pages.map((t, i) => (
            <Slab
              key={`p${i}`}
              x={t.x}
              y={t.y}
              w={t.w}
              h={t.h}
              d={hit(t.keys) ? 0.1 : 0.03}
              color={t.keys.length ? palette["accent-300"] : palette["ink-300"]}
              opacity={op(0)}
            />
          ))}
          {layout.strips.map((s, i) => (
            <Slab
              key={`s${i}`}
              x={s.x}
              y={s.y}
              z={s.keys.length ? 0.25 : 0}
              w={s.w}
              h={s.h}
              d={0.05}
              color={hit(s.keys) ? palette["ink-900"] : s.keys.length ? palette["accent-500"] : palette["line-strong"]}
              opacity={op(1)}
            />
          ))}
          {layout.nodes.map((n) => {
            const selected = n.key === selectedKey;
            const size = selected ? n.w * 1.3 : n.w;
            return (
              <Slab
                key={n.key}
                x={n.x}
                y={n.y}
                z={0.12}
                w={size}
                h={size}
                d={size}
                color={selected ? palette["ink-900"] : n.cited ? palette["accent-500"] : palette["ink-500"]}
                opacity={op(2)}
                onClick={
                  onSelect
                    ? (e) => {
                        e.stopPropagation();
                        onSelect(n.key);
                      }
                    : undefined
                }
              />
            );
          })}
          <Slab x={layout.answer.x} y={layout.answer.y} w={layout.answer.w} h={layout.answer.h} d={0.08} color={palette["ink-300"]} opacity={op(3)} />
          {[1.0, 0.65, 0.3, -0.05, -0.4, -0.75].map((dy, i) => (
            <Slab
              key={`a${i}`}
              x={layout.answer.x - (i % 3 === 2 ? 0.2 : 0)}
              y={layout.answer.y + dy}
              z={0.05}
              w={i % 3 === 2 ? 0.7 : 1.1}
              h={0.08}
              d={0.01}
              color={palette["ink-500"]}
              opacity={op(3)}
            />
          ))}
          <Links links={layout.links} palette={palette} selectedKey={selectedKey} activeStage={activeStage} />
        </group>
      </Canvas>
    </div>
  );
}
