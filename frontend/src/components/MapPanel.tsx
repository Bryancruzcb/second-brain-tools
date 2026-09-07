"use client";

import { graphEdges, graphNodes, notes } from "@/data/mock";
import { GlowOutline } from "./GlowOutline";

type Props = {
  activeId: string | null;
  onNodeClick: (id: string) => void;
  sectionGlow?: boolean;
};

const clusterMeta: Record<
  string,
  { label: string; fill: string; cx: number; cy: number; rx: number; ry: number }
> = {
  systems: {
    label: "Systems",
    fill: "rgba(94, 106, 210, 0.07)",
    cx: 310,
    cy: 150,
    rx: 110,
    ry: 78,
  },
  learning: {
    label: "Learning",
    fill: "rgba(52, 168, 83, 0.06)",
    cx: 195,
    cy: 78,
    rx: 72,
    ry: 48,
  },
  ai: {
    label: "AI",
    fill: "rgba(94, 106, 210, 0.05)",
    cx: 155,
    cy: 235,
    rx: 70,
    ry: 52,
  },
  graph: {
    label: "Graph",
    fill: "rgba(201, 137, 42, 0.07)",
    cx: 485,
    cy: 215,
    rx: 72,
    ry: 55,
  },
  meetings: {
    label: "Meetings",
    fill: "rgba(110, 110, 115, 0.06)",
    cx: 355,
    cy: 285,
    rx: 70,
    ry: 48,
  },
  inbox: {
    label: "Inbox",
    fill: "rgba(217, 83, 79, 0.05)",
    cx: 88,
    cy: 115,
    rx: 58,
    ry: 42,
  },
  templates: {
    label: "Templates",
    fill: "rgba(110, 110, 115, 0.05)",
    cx: 560,
    cy: 135,
    rx: 62,
    ry: 44,
  },
};

function wrapTitle(title: string, maxChars = 16): string[] {
  if (title.length <= maxChars) return [title];
  const words = title.split(" ");
  if (words.length === 1) {
    return [title.slice(0, maxChars - 1) + "…"];
  }
  let line1 = words[0];
  let i = 1;
  while (i < words.length && (line1 + " " + words[i]).length <= maxChars) {
    line1 += " " + words[i];
    i++;
  }
  const rest = words.slice(i).join(" ");
  if (!rest) return [line1];
  const line2 =
    rest.length <= maxChars ? rest : rest.slice(0, maxChars - 1) + "…";
  return [line1, line2];
}

export function MapPanel({ activeId, onNodeClick, sectionGlow }: Props) {
  const byId = Object.fromEntries(graphNodes.map((n) => [n.id, n]));
  const linkedCount = new Set(graphEdges.flat()).size;

  return (
    <GlowOutline
      id="map"
      className="bento-map h-full"
      glow={sectionGlow}
      radius={18}
    >
    <div className="card-elevated flex h-full min-h-[480px] flex-col overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-hairline px-5 py-4">
        <div className="min-w-0">
          <h3 className="text-[16px] font-medium tracking-[-0.02em]">Map</h3>
          <p className="mt-0.5 text-[12px] font-medium text-muted">
            Demo vault · {graphNodes.length} notes · {linkedCount} linked
          </p>
        </div>
        <span className="shrink-0 rounded-full bg-[var(--accent-softer)] px-2.5 py-1 text-[12px] font-medium text-[var(--accent)]">
          Neighborhood
        </span>
      </div>
      <div className="relative flex-1 bg-white" style={{ minHeight: 380 }}>
        <svg
          viewBox="0 0 640 400"
          className="absolute inset-0 h-full w-full"
          role="img"
          aria-label="Vault neighborhood map"
          preserveAspectRatio="xMidYMid meet"
        >
          <defs>
            <pattern id="dots" width="20" height="20" patternUnits="userSpaceOnUse">
              <circle cx="1" cy="1" r="0.8" fill="#E8E8ED" />
            </pattern>
          </defs>
          <rect width="640" height="400" fill="url(#dots)" />

          {Object.entries(clusterMeta).map(([key, c]) => (
            <g key={key} pointerEvents="none">
              <ellipse
                cx={c.cx}
                cy={c.cy}
                rx={c.rx}
                ry={c.ry}
                fill={c.fill}
                stroke="rgba(210, 210, 215, 0.55)"
                strokeWidth="1"
              />
              <text
                x={c.cx - c.rx + 10}
                y={c.cy - c.ry + 14}
                fill="#A1A1A6"
                fontSize="10"
                fontWeight={550}
                fontFamily="Inter, system-ui, sans-serif"
                letterSpacing="0.02em"
              >
                {c.label}
              </text>
            </g>
          ))}

          {graphEdges.map(([a, b]) => {
            const na = byId[a];
            const nb = byId[b];
            if (!na || !nb) return null;
            const lit = activeId === a || activeId === b;
            return (
              <line
                key={`${a}-${b}`}
                x1={na.x}
                y1={na.y}
                x2={nb.x}
                y2={nb.y}
                stroke={lit ? "#5E6AD2" : "#C8C8CD"}
                strokeWidth={lit ? 1.85 : 1.35}
                strokeOpacity={lit ? 0.75 : 0.95}
              />
            );
          })}

          {graphNodes.map((node) => {
            const note = notes.find((n) => n.id === node.id);
            const active = activeId === node.id;
            const lines = wrapTitle(note?.title ?? node.id, 18);
            return (
              <g
                key={node.id}
                className="map-node"
                onClick={(e) => {
                  onNodeClick(node.id);
                  (e.currentTarget as SVGGElement).blur();
                  if (document.activeElement instanceof HTMLElement) {
                    document.activeElement.blur();
                  }
                }}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onNodeClick(node.id);
                    (e.currentTarget as SVGGElement).blur();
                  }
                }}
              >
                {active && (
                  <circle
                    cx={node.x}
                    cy={node.y}
                    r={node.r + 11}
                    fill="#5E6AD2"
                    fillOpacity="0.14"
                  />
                )}
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={active ? node.r + 2 : node.r}
                  fill={active ? "#5E6AD2" : "#fff"}
                  stroke="#5E6AD2"
                  strokeWidth={active ? 0 : 2}
                  strokeOpacity={active ? 1 : 0.55}
                />
                {!active && (
                  <circle
                    cx={node.x}
                    cy={node.y}
                    r={Math.max(2, node.r - 3)}
                    fill="#5E6AD2"
                    fillOpacity="0.35"
                  />
                )}
                <text
                  className="map-label"
                  x={node.x}
                  y={node.y + node.r + 14}
                  textAnchor="middle"
                  fill={active ? "#1D1D1F" : "#6E6E73"}
                  fontSize="10.5"
                  fontWeight={active ? 550 : 450}
                  fontFamily="Inter, system-ui, sans-serif"
                >
                  {lines.map((line, i) => (
                    <tspan
                      key={i}
                      x={node.x}
                      dy={i === 0 ? 0 : 12}
                    >
                      {line}
                    </tspan>
                  ))}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
    </GlowOutline>
  );
}
