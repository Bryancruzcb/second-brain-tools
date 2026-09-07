"use client";

import { useEffect, useMemo, useState } from "react";
import { ApiError, fetchGraph, layoutGraph } from "@/lib/api";
import type { GraphNode } from "@/types";
import { GlowOutline } from "./GlowOutline";

type Props = {
  activeId: string | null;
  onNodeClick: (id: string) => void;
  sectionGlow?: boolean;
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

type Laid = {
  nodes: GraphNode[];
  edges: [string, string][];
  labels: Record<string, string>;
  totalNodes: number;
  shownNodes: number;
};

export function MapPanel({ activeId, onNodeClick, sectionGlow }: Props) {
  const [laid, setLaid] = useState<Laid | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const g = await fetchGraph();
        if (cancelled) return;
        setLaid(layoutGraph(g.nodes || [], g.edges || []));
      } catch (e) {
        if (cancelled) return;
        setError(
          e instanceof ApiError ? e.message : "Could not load vault graph.",
        );
        setLaid(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const byId = useMemo(() => {
    if (!laid) return {} as Record<string, GraphNode>;
    return Object.fromEntries(laid.nodes.map((n) => [n.id, n]));
  }, [laid]);

  const linkedCount = laid
    ? new Set(laid.edges.flat()).size
    : 0;

  const subtitle = loading
    ? "Loading vault graph…"
    : error
      ? "Backend unavailable"
      : laid
        ? `Vault · ${laid.totalNodes} notes · showing ${laid.shownNodes} · ${linkedCount} linked`
        : "No graph data";

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
          <p className="mt-0.5 truncate text-[12px] font-medium text-muted">
            {subtitle}
          </p>
        </div>
        <span className="shrink-0 rounded-full bg-[var(--accent-softer)] px-2.5 py-1 text-[12px] font-medium text-[var(--accent)]">
          Neighborhood
        </span>
      </div>
      <div className="relative flex-1 bg-white" style={{ minHeight: 380 }}>
        {error ? (
          <div className="absolute inset-0 flex items-center justify-center px-6 text-center text-[13px] text-[#b42318]">
            {error}
          </div>
        ) : loading || !laid ? (
          <div className="absolute inset-0 flex items-center justify-center text-[13px] text-muted">
            Loading map…
          </div>
        ) : laid.nodes.length === 0 ? (
          <div className="absolute inset-0 flex items-center justify-center text-[13px] text-muted">
            No notes in the graph yet. Run an index/scan on the backend.
          </div>
        ) : (
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

          {laid.edges.map(([a, b]) => {
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

          {laid.nodes.map((node) => {
            const title = laid.labels[node.id] ?? node.id;
            const active = activeId === node.id;
            const lines = wrapTitle(title, 18);
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
        )}
      </div>
    </div>
    </GlowOutline>
  );
}
