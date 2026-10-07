"use client";

import { useEffect, useMemo, useRef, useState, type PointerEvent, type WheelEvent } from "react";
import { ApiError, fetchGraph, layoutGraph } from "@/lib/api";
import type { GraphLayout } from "@/lib/api";
import type { GraphNode } from "@/types";
import { useWorkspace } from "./context";
import { NoteInspector } from "./NoteInspector";

function wrapTitle(title: string, maxChars = 16): string[] {
  if (title.length <= maxChars) return [title];
  const words = title.split(" ");
  if (words.length === 1) return [title.slice(0, maxChars - 1) + "…"];
  let line1 = words[0];
  let i = 1;
  while (i < words.length && (line1 + " " + words[i]).length <= maxChars) {
    line1 += " " + words[i];
    i++;
  }
  const rest = words.slice(i).join(" ");
  if (!rest) return [line1];
  return [line1, rest.length <= maxChars ? rest : rest.slice(0, maxChars - 1) + "…"];
}

const VB = { w: 960, h: 560 };

const CLUSTER_FILL: Record<string, string> = {
  Home: "color-mix(in srgb, var(--accent) 12%, transparent)",
  Memory: "color-mix(in srgb, var(--sky) 12%, transparent)",
  Projects: "color-mix(in srgb, var(--warning) 11%, transparent)",
  School: "color-mix(in srgb, var(--success) 12%, transparent)",
  Career: "color-mix(in srgb, var(--sky) 9%, transparent)",
  Imported: "color-mix(in srgb, var(--muted) 14%, transparent)",
  "Imported Files": "color-mix(in srgb, var(--muted) 14%, transparent)",
  Vault: "color-mix(in srgb, var(--muted) 12%, transparent)",
  Chats: "color-mix(in srgb, var(--danger) 12%, transparent)",
};

function topInCluster(nodes: GraphNode[], cluster: string): string | null {
  let best: GraphNode | null = null;
  for (const n of nodes) {
    if (n.cluster !== cluster) continue;
    if (!best || n.r > best.r) best = n;
  }
  return best ? best.id : null;
}

export function MapView() {
  const { mapFocusId, selectNote, selectedNoteId } = useWorkspace();
  const [raw, setRaw] = useState<{
    nodes: Parameters<typeof layoutGraph>[0];
    edges: Parameters<typeof layoutGraph>[1];
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [cluster, setCluster] = useState("all");
  const [includeChats, setIncludeChats] = useState(false);
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [cam, setCam] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef({ on: false, x: 0, y: 0, cx: 0, cy: 0 });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const g = await fetchGraph();
        if (cancelled) return;
        setRaw({ nodes: g.nodes || [], edges: g.edges || [] });
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof ApiError ? e.message : "Could not load vault graph.");
        setRaw(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const laid: GraphLayout | null = useMemo(() => {
    if (!raw) return null;
    return layoutGraph(raw.nodes, raw.edges, {
      width: VB.w,
      height: VB.h,
      maxNodes: 28,
      includeChats,
    });
  }, [raw, includeChats]);

  const clusters = useMemo(() => {
    if (!laid) return [];
    return laid.clusters.map((c) => c.label);
  }, [laid]);

  const visibleIds = useMemo(() => {
    if (!laid) return new Set<string>();
    const q = query.trim().toLowerCase();
    const ids = new Set<string>();
    for (const n of laid.nodes) {
      if (cluster !== "all" && n.cluster !== cluster) continue;
      const label = (laid.labels[n.id] || n.id).toLowerCase();
      if (q && !label.includes(q) && !n.id.toLowerCase().includes(q)) continue;
      ids.add(n.id);
    }
    return ids;
  }, [laid, query, cluster]);

  const byId = useMemo(() => {
    if (!laid) return {} as Record<string, GraphNode>;
    return Object.fromEntries(laid.nodes.map((n) => [n.id, n]));
  }, [laid]);

  const linkedCount = laid ? new Set(laid.edges.flat()).size : 0;
  const hoverLabel = hoverId && laid ? laid.labels[hoverId] || hoverId : null;
  const hoverNode = hoverId ? byId[hoverId] : null;

  const onWheel = (e: WheelEvent<SVGSVGElement>) => {
    e.preventDefault();
    const factor = e.deltaY > 0 ? 0.92 : 1.08;
    setCam((c) => ({ ...c, k: Math.min(3, Math.max(0.4, c.k * factor)) }));
  };

  const onPointerDown = (e: PointerEvent<SVGSVGElement>) => {
    if ((e.target as Element).closest(".map-node")) return;
    drag.current = { on: true, x: e.clientX, y: e.clientY, cx: cam.x, cy: cam.y };
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: PointerEvent<SVGSVGElement>) => {
    if (!drag.current.on) return;
    setCam({
      x: drag.current.cx + (e.clientX - drag.current.x),
      y: drag.current.cy + (e.clientY - drag.current.y),
      k: cam.k,
    });
  };

  const onPointerUp = (e: PointerEvent<SVGSVGElement>) => {
    drag.current.on = false;
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
  };

  const subtitle = loading
    ? "Loading vault graph…"
    : error
      ? "Backend unavailable"
      : laid
        ? `${laid.totalNodes} notes · showing ${visibleIds.size} of ${laid.shownNodes}${
            laid.hiddenChats ? ` · ${laid.hiddenChats} chats hidden` : ""
          } · ${linkedCount} linked`
        : "No graph data";

  return (
    <div className="flex min-h-0 min-w-0 flex-1">
      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex flex-wrap items-end justify-between gap-3 border-b border-hairline px-4 py-3">
          <div>
            <h2 className="text-[15px] font-medium tracking-[-0.02em]">Map</h2>
            <p className="mt-0.5 text-[12px] text-muted">{subtitle}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="search"
              className="focus-ring h-8 w-40 rounded-[7px] border border-hairline bg-elevated px-2 text-[12px]"
              placeholder="Filter labels"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Filter graph by label"
            />
            <select
              className="focus-ring h-8 rounded-[7px] border border-hairline bg-elevated px-2 text-[12px]"
              value={cluster}
              onChange={(e) => setCluster(e.target.value)}
              aria-label="Filter graph by cluster"
            >
              <option value="all">All folders</option>
              {clusters.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <label className="flex h-8 items-center gap-1.5 rounded-[7px] border border-hairline bg-elevated px-2 text-[12px] text-muted">
              <input
                type="checkbox"
                checked={includeChats}
                onChange={(e) => setIncludeChats(e.target.checked)}
              />
              Chats
            </label>
            <button
              type="button"
              className="btn btn-icon"
              aria-label="Zoom in"
              onClick={() => setCam((c) => ({ ...c, k: Math.min(3, c.k * 1.15) }))}
            >
              +
            </button>
            <button
              type="button"
              className="btn btn-icon"
              aria-label="Zoom out"
              onClick={() => setCam((c) => ({ ...c, k: Math.max(0.4, c.k / 1.15) }))}
            >
              −
            </button>
            <button
              type="button"
              className="btn btn-ghost btn-compact"
              onClick={() => setCam({ x: 0, y: 0, k: 1 })}
            >
              Reset
            </button>
          </div>
        </header>
        <div className="relative min-h-0 flex-1 bg-page">
          {error ? (
            <p className="absolute inset-0 flex items-center justify-center px-6 text-center text-[13px] text-[var(--danger)]">
              {error}
            </p>
          ) : loading || !laid ? (
            <p className="absolute inset-0 flex items-center justify-center text-[13px] text-muted">
              Loading map…
            </p>
          ) : laid.nodes.length === 0 ? (
            <p className="absolute inset-0 flex items-center justify-center text-[13px] text-muted">
              No notes in the graph yet. Run a scan on the backend.
            </p>
          ) : (
            <svg
              viewBox={`0 0 ${VB.w} ${VB.h}`}
              className="absolute inset-0 h-full w-full cursor-grab active:cursor-grabbing"
              role="img"
              aria-label="Vault neighborhood map"
              preserveAspectRatio="xMidYMid meet"
              onWheel={onWheel}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMove}
              onPointerUp={onPointerUp}
              onPointerCancel={onPointerUp}
            >
              <defs>
                <pattern id="map-dots" width="20" height="20" patternUnits="userSpaceOnUse">
                  <circle cx="1" cy="1" r="0.7" fill="var(--hairline)" />
                </pattern>
              </defs>
              <rect width={VB.w} height={VB.h} fill="url(#map-dots)" />
              <g transform={`translate(${cam.x} ${cam.y}) scale(${cam.k})`}>
                {laid.clusters.map((c) => {
                  const visible = laid.nodes.some(
                    (n) => n.cluster === c.key && visibleIds.has(n.id),
                  );
                  if (!visible) return null;
                  return (
                    <g key={c.key} pointerEvents="none">
                      <ellipse
                        cx={c.cx}
                        cy={c.cy}
                        rx={c.rx}
                        ry={c.ry}
                        fill={CLUSTER_FILL[c.label] || CLUSTER_FILL.Vault}
                        stroke="var(--hairline)"
                        strokeWidth="1"
                      />
                      <text
                        x={c.cx - c.rx + 10}
                        y={c.cy - c.ry + 14}
                        fill="var(--muted)"
                        fontSize="11"
                        fontFamily="IBM Plex Mono, ui-monospace, monospace"
                      >
                        {c.label}
                      </text>
                    </g>
                  );
                })}
                {laid.edges.map(([a, b]) => {
                  if (!visibleIds.has(a) || !visibleIds.has(b)) return null;
                  const na = byId[a];
                  const nb = byId[b];
                  if (!na || !nb) return null;
                  const lit = mapFocusId === a || mapFocusId === b;
                  return (
                    <line
                      key={`${a}-${b}`}
                      x1={na.x}
                      y1={na.y}
                      x2={nb.x}
                      y2={nb.y}
                      stroke={lit ? "var(--sky)" : "var(--hairline)"}
                      strokeWidth={lit ? 1.8 : 1.2}
                    />
                  );
                })}
                {laid.nodes.map((node) => {
                  if (!visibleIds.has(node.id)) return null;
                  const title = laid.labels[node.id] ?? node.id;
                  const active = mapFocusId === node.id;
                  const hovered = hoverId === node.id;
                  const lines = wrapTitle(title, 16);
                  const showLabel =
                    active ||
                    hovered ||
                    cam.k >= 1.25 ||
                    topInCluster(laid.nodes, node.cluster) === node.id;
                  return (
                    <g
                      key={node.id}
                      className="map-node"
                      role="button"
                      tabIndex={0}
                      onMouseEnter={() => setHoverId(node.id)}
                      onMouseLeave={() => setHoverId(null)}
                      onClick={() => selectNote(node.id, { askContext: true })}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          selectNote(node.id, { askContext: true });
                        }
                      }}
                    >
                      {active && (
                        <circle
                          cx={node.x}
                          cy={node.y}
                          r={node.r + 10}
                          fill="var(--accent)"
                          fillOpacity="0.18"
                        />
                      )}
                      <circle
                        cx={node.x}
                        cy={node.y}
                        r={active ? node.r + 2 : node.r}
                        fill={active ? "var(--accent)" : "var(--elevated)"}
                        stroke="var(--accent)"
                        strokeWidth={active ? 0 : 1.5}
                      />
                      {!active && (
                        <circle
                          cx={node.x}
                          cy={node.y}
                          r={Math.max(2, node.r - 3)}
                          fill="var(--accent)"
                          fillOpacity="0.35"
                        />
                      )}
                      {showLabel && (
                        <text
                          className="map-label"
                          x={node.x}
                          y={node.y + node.r + 14}
                          textAnchor="middle"
                          fill={active ? "var(--ink)" : "var(--muted)"}
                          fontSize="11"
                          fontFamily="IBM Plex Mono, ui-monospace, monospace"
                        >
                          {lines.map((line, i) => (
                            <tspan key={i} x={node.x} dy={i === 0 ? 0 : 12}>
                              {line}
                            </tspan>
                          ))}
                        </text>
                      )}
                    </g>
                  );
                })}
              </g>
            </svg>
          )}
          {hoverNode && hoverLabel && (
            <div
              className="pointer-events-none absolute rounded-[7px] border border-hairline bg-elevated px-2 py-1 text-[12px] shadow-[var(--shadow)]"
              style={{ left: 12, bottom: 12 }}
              role="tooltip"
            >
              <span className="font-medium">{hoverLabel}</span>
              <span className="mono ml-2 text-[10px] text-muted">{hoverNode.cluster}</span>
            </div>
          )}
        </div>
      </section>
      {selectedNoteId && (
        <aside className="w-[min(24rem,38%)] shrink-0 border-l border-hairline bg-panel max-md:absolute max-md:inset-0 max-md:w-full max-md:border-l-0">
          <NoteInspector onClose={() => selectNote(null)} />
        </aside>
      )}
    </div>
  );
}
