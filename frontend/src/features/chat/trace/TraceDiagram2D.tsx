/**
 * 2D (SVG) rendering of the Evidence Trace layout. Used when WebGL is unavailable,
 * on small screens, with reduced motion, on user preference, while the 3D module
 * loads, and if it fails. Decorative for assistive technology: the adjacent stage
 * panel carries the same information as text.
 */

import { VIEW, type Box } from "./layout";
import { DIM, type SceneProps } from "./sceneProps";

const rect = (b: Box) => ({ x: b.x - b.w / 2, y: -b.y - b.h / 2, width: b.w, height: b.h });

export function TraceDiagram2D({ layout, selectedKey, activeStage, onSelect }: SceneProps) {
  const opacity = (station: number) => (activeStage === null || activeStage === station ? 1 : DIM);
  const hit = (keys: string[]) => selectedKey !== null && keys.includes(selectedKey);

  return (
    <svg
      viewBox={`${-VIEW.width / 2} ${-VIEW.height / 2} ${VIEW.width} ${VIEW.height}`}
      preserveAspectRatio="xMidYMid meet"
      className="h-full w-full"
      aria-hidden="true"
      data-testid="trace-2d"
    >
      <g opacity={opacity(0)}>
        {layout.pages.map((tile, i) => (
          <rect
            key={`p${i}`}
            {...rect(tile)}
            rx={0.03}
            fill={tile.keys.length ? "var(--accent-300)" : "var(--ink-300)"}
            stroke={hit(tile.keys) ? "var(--ink-900)" : "var(--line-strong)"}
            strokeWidth={hit(tile.keys) ? 0.04 : 0.015}
          />
        ))}
      </g>
      {layout.links.map((link, i) => {
        const selected = link.key === selectedKey;
        const color =
          link.kind === "evidence-answer" || selected ? "var(--accent-500)" : "var(--ink-500)";
        return (
          <line
            key={`l${i}`}
            x1={link.from[0]}
            y1={-link.from[1]}
            x2={link.to[0]}
            y2={-link.to[1]}
            stroke={selected ? "var(--ink-900)" : color}
            strokeOpacity={(selected ? 1 : link.strength) * opacity(link.station)}
            strokeWidth={selected ? 0.04 : 0.022}
          />
        );
      })}
      <g opacity={opacity(1)}>
        {layout.strips.map((strip, i) => (
          <rect
            key={`s${i}`}
            {...rect({ ...strip, x: strip.x + (strip.keys.length ? 0.12 : 0) })}
            rx={0.01}
            fill={strip.keys.length ? "var(--accent-500)" : "var(--line-strong)"}
            stroke={hit(strip.keys) ? "var(--ink-900)" : "none"}
            strokeWidth={0.03}
          />
        ))}
      </g>
      <g opacity={opacity(2)}>
        {layout.nodes.map((node) => {
          const selected = node.key === selectedKey;
          const grow = selected ? 1.25 : 1;
          return (
            <rect
              key={node.key}
              {...rect({ ...node, w: node.w * grow, h: node.h * grow })}
              rx={0.04}
              fill={node.cited ? "var(--accent-500)" : "var(--ink-500)"}
              stroke={selected ? "var(--ink-900)" : "none"}
              strokeWidth={0.05}
              style={onSelect ? { cursor: "pointer" } : undefined}
              onClick={onSelect ? () => onSelect(node.key) : undefined}
            />
          );
        })}
      </g>
      <g opacity={opacity(3)}>
        <rect {...rect(layout.answer)} rx={0.06} fill="var(--paper-200)" stroke="var(--ink-500)" strokeWidth={0.03} />
        {[1.0, 0.65, 0.3, -0.05, -0.4, -0.75].map((dy, i) => (
          <rect
            key={i}
            x={layout.answer.x - 0.55}
            y={-(layout.answer.y + dy) - 0.04}
            width={i % 3 === 2 ? 0.7 : 1.1}
            height={0.08}
            fill="var(--ink-500)"
          />
        ))}
      </g>
    </svg>
  );
}
