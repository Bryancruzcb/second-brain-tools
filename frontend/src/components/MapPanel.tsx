"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  fetchGraph,
  layoutGraph,
  type BackendGraphEdge,
  type BackendGraphNode,
} from "@/lib/api";
import type { GraphNode } from "@/types";

type Props = {
  activeId: string | null;
  onNodeClick: (id: string) => void;
};

/** Layout size before the container has been measured (server render, first paint). */
const DEFAULT_W = 960;
const DEFAULT_H = 560;
const MIN_H = 340;
const MAX_H = 600;
/** Always-visible labels beyond the active node and its neighbours. */
const LABEL_BUDGET = 28;
const LABEL_FONT = 11.5;
const LABEL_LINE = LABEL_FONT + 1.5;
const LABEL_MAX_CHARS = 18;

type Laid = ReturnType<typeof layoutGraph>;
type Raw = { nodes: BackendGraphNode[]; edges: BackendGraphEdge[] };

function wrapTitle(title: string, maxChars = LABEL_MAX_CHARS): string[] {
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

type Box = { x1: number; y1: number; x2: number; y2: number };

/** Where a label sits relative to its node; tried in this order. */
type Placement = "below" | "above" | "right" | "left";
const PLACEMENTS: Placement[] = ["below", "above", "right", "left"];
const LABEL_GAP = 5;

/** Approximate bounds of a label at the given placement. */
function labelBox(node: GraphNode, lines: string[], placement: Placement): Box {
  const w = Math.max(...lines.map((l) => l.length)) * LABEL_FONT * 0.56;
  const h = lines.length * LABEL_LINE;
  const gap = node.r + LABEL_GAP;
  switch (placement) {
    case "below":
      return { x1: node.x - w / 2, y1: node.y + gap, x2: node.x + w / 2, y2: node.y + gap + h };
    case "above":
      return { x1: node.x - w / 2, y1: node.y - gap - h, x2: node.x + w / 2, y2: node.y - gap };
    case "right":
      return { x1: node.x + gap, y1: node.y - h / 2, x2: node.x + gap + w, y2: node.y + h / 2 };
    case "left":
      return { x1: node.x - gap - w, y1: node.y - h / 2, x2: node.x - gap, y2: node.y + h / 2 };
  }
}

/** SVG text attributes for a placement: anchor plus the first line's baseline. */
function labelAnchor(
  node: GraphNode,
  lines: number,
  placement: Placement,
): { x: number; y: number; textAnchor: "middle" | "start" | "end" } {
  const gap = node.r + LABEL_GAP;
  const h = lines * LABEL_LINE;
  switch (placement) {
    case "below":
      return { x: node.x, y: node.y + gap + LABEL_FONT, textAnchor: "middle" };
    case "above":
      return { x: node.x, y: node.y - gap - h + LABEL_FONT, textAnchor: "middle" };
    case "right":
      return { x: node.x + gap, y: node.y - h / 2 + LABEL_FONT, textAnchor: "start" };
    case "left":
      return { x: node.x - gap, y: node.y - h / 2 + LABEL_FONT, textAnchor: "end" };
  }
}

function nodeBox(node: GraphNode): Box {
  const r = node.r + 2;
  return { x1: node.x - r, y1: node.y - r, x2: node.x + r, y2: node.y + r };
}

function overlaps(a: Box, b: Box, pad = 3): boolean {
  return (
    a.x1 < b.x2 + pad && a.x2 > b.x1 - pad && a.y1 < b.y2 + pad && a.y2 > b.y1 - pad
  );
}

function neighboursOf(laid: Laid, id: string | null): Set<string> {
  const out = new Set<string>();
  if (!id) return out;
  for (const [a, b] of laid.edges) {
    if (a === id) out.add(b);
    if (b === id) out.add(a);
  }
  return out;
}

/**
 * Pick the nodes that carry an always-visible label and where each one sits:
 * the active node first, then its neighbours, then the most-linked notes. A
 * label is tried below, above, right, then left of its node and dropped when
 * every spot would cover another label, another node, or the canvas edge.
 * Dropped nodes still show their title on hover and focus, and every node
 * keeps an accessible name.
 */
function pickLabels(
  laid: Laid,
  activeId: string | null,
  neighbours: Set<string>,
  canvas: { w: number; h: number },
): Map<string, Placement> {
  const rank = (n: GraphNode) =>
    n.id === activeId ? 2 : neighbours.has(n.id) ? 1 : 0;
  const ordered = [...laid.nodes].sort(
    (a, b) =>
      rank(b) - rank(a) ||
      (laid.degrees[b.id] ?? 0) - (laid.degrees[a.id] ?? 0),
  );
  const obstacles = laid.nodes.map((n) => ({ id: n.id, box: nodeBox(n) }));
  const placed: Box[] = [];
  const chosen = new Map<string, Placement>();
  let budgetUsed = 0;
  for (const n of ordered) {
    if (rank(n) === 0 && budgetUsed >= LABEL_BUDGET) break;
    const lines = wrapTitle(laid.labels[n.id] ?? n.id);
    for (const placement of PLACEMENTS) {
      const box = labelBox(n, lines, placement);
      if (box.x1 < 0 || box.y1 < 0 || box.x2 > canvas.w || box.y2 > canvas.h) continue;
      if (placed.some((p) => overlaps(p, box))) continue;
      if (obstacles.some((o) => o.id !== n.id && overlaps(o.box, box, 1))) continue;
      placed.push(box);
      chosen.set(n.id, placement);
      if (rank(n) === 0) budgetUsed += 1;
      break;
    }
  }
  return chosen;
}

export function MapPanel({ activeId, onNodeClick }: Props) {
  const [raw, setRaw] = useState<Raw | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [size, setSize] = useState({ w: DEFAULT_W, h: DEFAULT_H });
  const fieldRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const g = await fetchGraph();
        if (cancelled) return;
        setRaw({ nodes: g.nodes || [], edges: g.edges || [] });
      } catch (e) {
        if (cancelled) return;
        setError(
          e instanceof ApiError ? e.message : "Could not load vault graph.",
        );
        setRaw(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Lay the graph out at 1 unit = 1 CSS px so labels stay legible at every width.
  useEffect(() => {
    const el = fieldRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0]?.contentRect.width ?? 0);
      if (w <= 0) return;
      const h = Math.round(Math.min(MAX_H, Math.max(MIN_H, w * 0.58)));
      setSize((s) => (s.w === w && s.h === h ? s : { w, h }));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const laid = useMemo(
    () =>
      raw
        ? layoutGraph(raw.nodes, raw.edges, {
            width: size.w,
            height: size.h,
            maxNodes: size.w < 640 ? 24 : 42,
          })
        : null,
    [raw, size],
  );

  const byId = useMemo(() => {
    if (!laid) return {} as Record<string, GraphNode>;
    return Object.fromEntries(laid.nodes.map((n) => [n.id, n]));
  }, [laid]);

  const neighbours = useMemo(
    () => (laid ? neighboursOf(laid, activeId) : new Set<string>()),
    [laid, activeId],
  );
  const labelled = useMemo(
    () =>
      laid
        ? pickLabels(laid, activeId, neighbours, size)
        : new Map<string, Placement>(),
    [laid, activeId, neighbours, size],
  );

  const linkedCount = laid ? new Set(laid.edges.flat()).size : 0;

  const subtitle = loading
    ? "Loading vault graph…"
    : error
      ? "Backend unavailable"
      : laid
        ? `${laid.totalNodes} notes · showing the ${laid.shownNodes} most linked · ${linkedCount} connected`
        : "No graph data";

  const hasGraph = Boolean(laid && !loading && !error && laid.nodes.length > 0);

  return (
    <div>
      <div className="section-heading">
        <div className="min-w-0">
          <h2 id="map-title" className="section-title">
            Map
          </h2>
          <p className="section-subtitle">{subtitle}</p>
        </div>
        {hasGraph && (
          <p className="section-hint">
            Labels mark the most-linked notes. Hover or focus any node for its
            title; click one to read it.
          </p>
        )}
      </div>

      <div ref={fieldRef} className="map-field">
        {error ? (
          <p className="map-message text-[#b42318]">{error}</p>
        ) : loading || !laid ? (
          <p className="map-message text-muted">Loading map…</p>
        ) : laid.nodes.length === 0 ? (
          <p className="map-message text-muted">
            No notes in the graph yet. Run an index/scan on the backend.
          </p>
        ) : (
          <svg
            viewBox={`0 0 ${size.w} ${size.h}`}
            width="100%"
            height={size.h}
            className="map-svg"
            role="group"
            aria-label={`Vault map: the ${laid.shownNodes} most-linked notes of ${laid.totalNodes}`}
          >
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
                  strokeOpacity={lit ? 0.75 : activeId ? 0.55 : 0.95}
                />
              );
            })}

            {laid.nodes.map((node) => {
              const title = laid.labels[node.id] ?? node.id;
              const active = activeId === node.id;
              const neighbour = neighbours.has(node.id);
              const degree = laid.degrees[node.id] ?? 0;
              const placement = labelled.get(node.id);
              const lines = wrapTitle(title);
              const anchor = labelAnchor(node, lines.length, placement ?? "below");
              const linkWord = degree === 1 ? "link" : "links";
              return (
                <g
                  key={node.id}
                  className="map-node"
                  role="button"
                  tabIndex={0}
                  aria-label={`${title}, ${degree} ${linkWord}`}
                  aria-pressed={active}
                  onClick={() => onNodeClick(node.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onNodeClick(node.id);
                    }
                  }}
                >
                  <title>{`${title} · ${degree} ${linkWord}`}</title>
                  <circle
                    className="map-focus-ring"
                    cx={node.x}
                    cy={node.y}
                    r={node.r + 6}
                    fill="none"
                    stroke="#5E6AD2"
                    strokeWidth="2"
                  />
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
                    strokeOpacity={active ? 1 : neighbour ? 0.95 : 0.55}
                  />
                  {!active && (
                    <circle
                      cx={node.x}
                      cy={node.y}
                      r={Math.max(2, node.r - 3)}
                      fill="#5E6AD2"
                      fillOpacity={neighbour ? 0.6 : 0.35}
                    />
                  )}
                  <text
                    className={`map-label ${placement ? "" : "map-label-quiet"}`}
                    x={anchor.x}
                    y={anchor.y}
                    textAnchor={anchor.textAnchor}
                    fill={active ? "#1D1D1F" : "#6E6E73"}
                    fontSize={LABEL_FONT}
                    fontWeight={active || neighbour ? 550 : 450}
                    fontFamily="Inter, system-ui, sans-serif"
                    aria-hidden
                  >
                    {lines.map((line, i) => (
                      <tspan key={i} x={anchor.x} dy={i === 0 ? 0 : LABEL_LINE}>
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
  );
}
