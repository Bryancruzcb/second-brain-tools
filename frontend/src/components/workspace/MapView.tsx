"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { Maximize2, Minus, Plus } from "lucide-react";
import { layoutGraph, type GraphLayout } from "@/lib/api";
import { folderColor } from "@/lib/folders";
import { useWorkspace } from "./context";
import { MapInspector, type InspectorNeighbor } from "./MapInspector";

type ColorBy = "folder" | "label";
type Camera = { x: number; y: number; k: number };

const EDGE_COLOR = "#3A4048";
const RING_COLOR = "#111316";
const NO_LABEL_COLOR = "#5B616A";
const CHAT_COLOR = "var(--text-tertiary)";
const MAX_ZOOM = 4;

/** Folder color, with chats (which have no folder of their own) in grey. */
function clusterColor(cluster: string): string {
  return cluster === "Chats" ? "var(--text-tertiary)" : folderColor(cluster);
}

/** Screen radius grows gently with zoom: r·√k, clamped, so dots stay legible. */
function nodeScale(k: number): number {
  return Math.min(1.4, Math.max(0.7, Math.sqrt(k))) / k;
}

function fitCamera(layout: GraphLayout, w: number, h: number): Camera {
  const k = Math.min(2, Math.max(0.04, Math.min(w / layout.width, h / layout.height) * 0.94));
  return { k, x: (w - layout.width * k) / 2, y: (h - layout.height * k) / 2 };
}

/** Nodes that get a permanent label: the best-linked note(s) of each folder. */
function pickHubs(layout: GraphLayout): Set<string> {
  const byCluster = new Map<string, GraphLayout["nodes"]>();
  for (const n of layout.nodes) {
    if (n.chat) continue;
    const list = byCluster.get(n.cluster) || [];
    list.push(n);
    byCluster.set(n.cluster, list);
  }
  const hubs = new Set<string>();
  for (const list of byCluster.values()) {
    const ranked = [...list].sort((a, b) => b.degree - a.degree);
    const take = list.length > 80 ? 2 : 1;
    for (const n of ranked.slice(0, take)) if (n.degree > 0 || list.length === 1) hubs.add(n.id);
  }
  return hubs;
}

export function MapView() {
  const {
    graphNodes,
    graphEdges,
    graphStatus,
    folders,
    chatCount,
    folderFilter,
    setFolderFilter,
    mapFocusId,
    selectNote,
  } = useWorkspace();

  const [colorBy, setColorBy] = useState<ColorBy>("folder");
  const [includeChats, setIncludeChats] = useState(false);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [cam, setCam] = useState<Camera>({ x: 0, y: 0, k: 1 });
  const [fittedFor, setFittedFor] = useState<string | null>(null);
  const [panning, setPanning] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ id: number; x: number; y: number; cx: number; cy: number } | null>(
    null,
  );

  const layout = useMemo(
    () => layoutGraph(graphNodes, graphEdges, { width: 600, height: 500, includeChats }),
    [graphNodes, graphEdges, includeChats],
  );

  const tagsById = useMemo(() => {
    const m = new Map<string, string[]>();
    for (const n of graphNodes) m.set(n.id, n.tags || []);
    return m;
  }, [graphNodes]);

  const byId = useMemo(
    () => new Map(layout.nodes.map((n) => [n.id, n])),
    [layout],
  );

  const neighbors = useMemo(() => {
    const m = new Map<string, string[]>();
    for (const [a, b] of layout.edges) {
      (m.get(a) || m.set(a, []).get(a)!).push(b);
      (m.get(b) || m.set(b, []).get(b)!).push(a);
    }
    return m;
  }, [layout]);

  const hubs = useMemo(() => pickHubs(layout), [layout]);

  // Default selection: the most-connected note.
  const defaultId = useMemo(() => {
    let best: GraphLayout["nodes"][number] | null = null;
    for (const n of layout.nodes) {
      if (n.chat) continue;
      if (!best || n.degree > best.degree) best = n;
    }
    return best?.id ?? null;
  }, [layout]);
  const selectedId = mapFocusId && byId.has(mapFocusId) ? mapFocusId : defaultId;
  const selected = selectedId ? byId.get(selectedId) ?? null : null;
  const selectedNeighbors = useMemo(
    () => new Set(selectedId ? neighbors.get(selectedId) || [] : []),
    [neighbors, selectedId],
  );

  const colorOf = useCallback(
    (id: string, cluster: string) => {
      if (colorBy === "folder") return clusterColor(cluster);
      const tag = (tagsById.get(id) || [])[0];
      return tag ? folderColor(tag.replace(/^#/, "")) : NO_LABEL_COLOR;
    },
    [colorBy, tagsById],
  );

  /* ---------- camera ---------- */

  useEffect(() => {
    const el = panelRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize((s) =>
        s && Math.abs(s.w - width) < 1 && Math.abs(s.h - height) < 1
          ? s
          : { w: width, h: height },
      );
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const fitKey = size ? `${layout.width}x${layout.height}:${layout.shownNodes}@${Math.round(size.w)}x${Math.round(size.h)}` : null;
  if (fitKey && size && fitKey !== fittedFor) {
    setFittedFor(fitKey);
    setCam(fitCamera(layout, size.w, size.h));
  }

  const minZoom = size ? fitCamera(layout, size.w, size.h).k * 0.5 : 0.05;
  const zoomLimits = useRef({ min: minZoom });
  useEffect(() => {
    zoomLimits.current.min = minZoom;
  }, [minZoom]);

  const zoomAt = useCallback((factor: number, sx: number, sy: number) => {
    setCam((c) => {
      const k = Math.min(MAX_ZOOM, Math.max(zoomLimits.current.min, c.k * factor));
      const f = k / c.k;
      return { k, x: sx - (sx - c.x) * f, y: sy - (sy - c.y) * f };
    });
  }, []);

  // Wheel zoom needs a non-passive listener to stop the page scrolling.
  useEffect(() => {
    const el = panelRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const factor = Math.exp(-e.deltaY * (e.deltaMode === 1 ? 0.05 : 0.0018));
      zoomAt(factor, e.clientX - rect.left, e.clientY - rect.top);
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [zoomAt]);

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    if ((e.target as Element).closest(".map-node, button")) return;
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, cx: cam.x, cy: cam.y };
    e.currentTarget.setPointerCapture(e.pointerId);
    setPanning(true);
  };
  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    setCam((c) => ({ ...c, x: d.cx + (e.clientX - d.x), y: d.cy + (e.clientY - d.y) }));
  };
  const endDrag = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (drag.current?.id !== e.pointerId) return;
    drag.current = null;
    setPanning(false);
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      /* already released */
    }
  };

  const zoomButton = (factor: number) => {
    if (!size) return;
    zoomAt(factor, size.w / 2, size.h / 2);
  };

  /* ---------- graph layers (memoised; panning only moves the camera) ---------- */

  const inFilter = useCallback(
    (cluster: string) => !folderFilter || cluster === folderFilter,
    [folderFilter],
  );

  const halos = useMemo(
    () =>
      layout.clusters.map((c, i) => {
        const color = clusterColor(c.key);
        const dim = folderFilter && c.key !== folderFilter;
        return (
          <g key={c.key} opacity={dim ? 0.35 : 1} pointerEvents="none">
            <defs>
              <radialGradient id={`halo-${i}`}>
                <stop offset="0%" stopColor={color} stopOpacity={0.12} />
                <stop offset="45%" stopColor={color} stopOpacity={0.04} />
                <stop offset="72%" stopColor={color} stopOpacity={0} />
              </radialGradient>
            </defs>
            <circle
              cx={c.cx}
              cy={c.cy}
              r={c.r}
              fill={`url(#halo-${i})`}
              stroke={color}
              strokeOpacity={0.18}
              className="map-w1"
            />
          </g>
        );
      }),
    [layout, folderFilter],
  );

  const edgeLayers = useMemo(() => {
    let normal = "";
    let dimmed = "";
    let chat = "";
    let chatDim = "";
    let lit = "";
    for (const [a, b] of layout.edges) {
      const na = byId.get(a);
      const nb = byId.get(b);
      if (!na || !nb) continue;
      const seg = `M${na.x.toFixed(1)} ${na.y.toFixed(1)}L${nb.x.toFixed(1)} ${nb.y.toFixed(1)}`;
      if (a === selectedId || b === selectedId) {
        lit += seg;
        continue;
      }
      const visible = inFilter(na.cluster) && inFilter(nb.cluster);
      if (na.chat || nb.chat) {
        if (visible) chat += seg;
        else chatDim += seg;
      } else if (visible) normal += seg;
      else dimmed += seg;
    }
    const common = {
      fill: "none",
      strokeLinecap: "round" as const,
    };
    return {
      under: (
        <g pointerEvents="none">
          {dimmed && <path d={dimmed} stroke={EDGE_COLOR} className="map-w125" opacity={0.15} {...common} />}
          {chatDim && (
            <path d={chatDim} stroke={EDGE_COLOR} className="map-w125 map-dash" opacity={0.15} {...common} />
          )}
          {normal && <path d={normal} stroke={EDGE_COLOR} className="map-w125" {...common} />}
          {chat && <path d={chat} stroke={EDGE_COLOR} className="map-w125 map-dash" {...common} />}
        </g>
      ),
      lit: lit ? (
        <path d={lit} stroke="var(--accent)" className="map-w2" pointerEvents="none" {...common} />
      ) : null,
    };
  }, [layout, byId, selectedId, inFilter]);

  const nodeLayer = useMemo(
    () =>
      layout.nodes.map((n) => {
        if (n.id === selectedId) return null; // drawn on top, below
        const title = layout.labels[n.id] ?? n.id;
        const color = n.chat ? CHAT_COLOR : colorOf(n.id, n.cluster);
        const neighbor = selectedNeighbors.has(n.id);
        const dim = !inFilter(n.cluster);
        return (
          <g
            key={n.id}
            className="map-node"
            transform={`translate(${n.x} ${n.y})`}
            opacity={dim ? 0.2 : 1}
            role="button"
            tabIndex={hubs.has(n.id) ? 0 : -1}
            aria-label={`${title}, ${n.cluster}, ${n.degree} links`}
            onClick={() => selectNote(n.id)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                selectNote(n.id);
              }
            }}
          >
            <title>{title}</title>
            <circle className="map-hit" r={16} fill="transparent" />
            <g className="map-dot">
              {neighbor && (
                <circle
                  r={n.r + 3}
                  fill="none"
                  stroke={n.chat ? CHAT_COLOR : clusterColor(n.cluster)}
                  strokeOpacity={0.6}
                  className="map-dw2"
                />
              )}
              {n.chat ? (
                <circle
                  r={n.r}
                  fill="var(--bg-page)"
                  stroke={color}
                  className="map-dw15"
                />
              ) : (
                <circle
                  r={n.r}
                  fill={color}
                  stroke={RING_COLOR}
                  className="map-dw2"
                />
              )}
              <circle
                className="map-focus map-dw2"
                r={n.r + 5}
                fill="none"
                stroke="var(--accent)"
              />
            </g>
          </g>
        );
      }),
    [layout, selectedId, selectedNeighbors, colorOf, inFilter, hubs, selectNote],
  );

  const selectedLayer = selected ? (
    <g
      className="map-node"
      transform={`translate(${selected.x} ${selected.y})`}
      role="button"
      tabIndex={0}
      aria-label={`${layout.labels[selected.id] ?? selected.id}, selected`}
      aria-pressed
    >
      <title>{layout.labels[selected.id] ?? selected.id}</title>
      <circle className="map-hit" r={16} fill="transparent" />
      <g className="map-dot">
        <circle r={selected.r + 14} fill="var(--accent)" opacity={0.14} />
        <circle r={selected.r + 8} fill="var(--accent)" opacity={0.12} />
        <circle
          r={selected.r + 2 + 3}
          fill="none"
          stroke="var(--accent)"
          className="map-dw2"
        />
        <circle
          r={selected.r + 2}
          fill={selected.chat ? "var(--bg-page)" : colorOf(selected.id, selected.cluster)}
          stroke={RING_COLOR}
          className="map-dw2"
        />
        <circle
          className="map-focus map-dw2"
          r={selected.r + 9}
          fill="none"
          stroke="var(--accent)"
        />
      </g>
    </g>
  ) : null;

  /* ---------- HTML overlays (labels stay 12px at any zoom) ---------- */

  const ns = nodeScale(cam.k);
  const toScreen = (x: number, y: number) => ({ left: x * cam.k + cam.x, top: y * cam.k + cam.y });
  const onScreen = (p: { left: number; top: number }, margin = 40) =>
    size != null &&
    p.left > -margin &&
    p.top > -margin &&
    p.left < size.w + margin &&
    p.top < size.h + margin;

  const labelIds = [...hubs].filter((id) => id !== selectedId);
  if (selectedId) labelIds.push(selectedId);

  /* ---------- inspector data ---------- */

  const inspectorNeighbors: InspectorNeighbor[] = useMemo(() => {
    if (!selectedId) return [];
    return (neighbors.get(selectedId) || [])
      .map((id) => byId.get(id))
      .filter((n): n is NonNullable<typeof n> => Boolean(n))
      .sort((a, b) => Number(a.chat) - Number(b.chat) || b.degree - a.degree)
      .map((n) => ({
        id: n.id,
        title: layout.labels[n.id] ?? n.id,
        folder: n.chat ? "Chat" : n.cluster,
        color: n.chat ? CHAT_COLOR : clusterColor(n.cluster),
        chat: n.chat,
      }));
  }, [selectedId, neighbors, byId, layout]);

  /* ---------- counts ---------- */

  const counts = useMemo(() => {
    let notes = 0;
    let chats = 0;
    for (const n of layout.nodes) {
      if (!inFilter(n.cluster)) continue;
      if (n.chat) chats += 1;
      else notes += 1;
    }
    let links = 0;
    for (const [a, b] of layout.edges) {
      const na = byId.get(a);
      const nb = byId.get(b);
      if (!na || !nb || na.chat || nb.chat) continue;
      if (inFilter(na.cluster) && inFilter(nb.cluster)) links += 1;
    }
    return { notes, chats, links };
  }, [layout, byId, inFilter]);

  const statusLine =
    graphStatus !== "ok"
      ? null
      : `${counts.notes.toLocaleString("en-US")} notes · ${counts.links.toLocaleString(
          "en-US",
        )} links · ${
          includeChats
            ? `${counts.chats.toLocaleString("en-US")} chats shown`
            : `${layout.hiddenChats.toLocaleString("en-US")} chats hidden`
        }`;

  /* ---------- render ---------- */

  let panelMessage: string | null = null;
  if (graphStatus === "loading") panelMessage = "Loading map…";
  else if (graphStatus === "error") panelMessage = "Couldn't load the map. Is the backend running on :8000?";
  else if (layout.nodes.length === 0) panelMessage = "No notes in the graph yet. Run a scan from Health.";

  return (
    <div className="min-h-0 min-w-0 flex-1 overflow-y-auto">
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4 px-7 pb-[18px] pt-[26px]">
        <div className="min-w-0">
          <h1 className="text-[26px] font-semibold leading-tight tracking-[-0.02em] text-primary">
            Map
          </h1>
          <p className="mt-1 text-[14px] text-secondary">
            See how your notes connect. Click any dot to explore its links.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <span id="map-color-by" className="text-[13px] text-tertiary">
              Color by
            </span>
            <div
              role="group"
              aria-labelledby="map-color-by"
              className="flex h-11 items-center rounded-button border border-control bg-surface p-[3px]"
            >
              {(["folder", "label"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  aria-pressed={colorBy === mode}
                  onClick={() => setColorBy(mode)}
                  className={`h-full rounded-[8px] px-3.5 text-[13px] font-medium transition-colors ${
                    colorBy === mode
                      ? "bg-segment-active text-primary"
                      : "text-secondary hover:text-primary"
                  }`}
                >
                  {mode === "folder" ? "Folder" : "Label"}
                </button>
              ))}
            </div>
          </div>
          <button
            type="button"
            aria-pressed={includeChats}
            onClick={() => setIncludeChats((v) => !v)}
            className="flex h-11 items-center gap-2.5 rounded-button border border-control bg-surface px-3.5 text-[13px] font-medium text-primary transition-colors hover:border-strong"
          >
            <span
              aria-hidden
              className={`relative h-[18px] w-8 shrink-0 rounded-chip transition-colors ${
                includeChats ? "bg-accent" : "bg-[#2E3238]"
              }`}
            >
              <span
                className={`absolute top-[3px] h-3 w-3 rounded-full transition-[left] ${
                  includeChats ? "left-[17px] bg-accent-ink" : "left-[3px] bg-secondary"
                }`}
              />
            </span>
            Show chats
            <span className="mono text-[12px] text-tertiary">
              {chatCount != null ? chatCount.toLocaleString("en-US") : "–"}
            </span>
          </button>
        </div>
      </header>

      <div className="flex flex-wrap items-center gap-2 px-7 pb-4">
        <div role="group" aria-label="Filter map by folder" className="flex flex-wrap items-center gap-2">
          <FilterChip
            label="All folders"
            active={!folderFilter}
            onClick={() => setFolderFilter(null)}
          />
          {folders.map((f) => (
            <FilterChip
              key={f.name}
              label={f.name}
              color={f.color}
              active={folderFilter === f.name}
              onClick={() => setFolderFilter(folderFilter === f.name ? null : f.name)}
            />
          ))}
        </div>
        {statusLine && (
          <p className="mono ml-auto pl-2 text-[12px] text-tertiary" aria-live="polite">
            {statusLine}
          </p>
        )}
      </div>

      <div className="flex gap-5 px-7 pb-7 max-[800px]:flex-col">
        <div
          ref={panelRef}
          className="map-panel relative aspect-[6/5] cursor-grab active:cursor-grabbing min-w-0 flex-1 touch-none select-none overflow-hidden rounded-card border border-divider"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
        >
          {panelMessage ? (
            <p
              className={`absolute inset-0 flex items-center justify-center px-6 text-center text-[14px] ${
                graphStatus === "error" ? "text-danger" : "text-tertiary"
              }`}
            >
              {panelMessage}
            </p>
          ) : (
            size && (
              <>
                {/* Pan/zoom is a CSS transform on this wrapper, so dragging is a
                    compositor move instead of repainting every dot. Stroke widths
                    divide by --k in CSS to stay constant on screen. */}
                <div
                  className={`map-world absolute left-0 top-0 origin-top-left ${
                    panning ? "will-change-transform" : ""
                  }`}
                  style={
                    {
                      width: layout.width,
                      height: layout.height,
                      transform: `translate(${cam.x}px, ${cam.y}px) scale(${cam.k})`,
                      "--k": cam.k,
                      "--ns": ns,
                      "--hit": 1 / cam.k,
                    } as CSSProperties
                  }
                >
                  <svg
                    width={layout.width}
                    height={layout.height}
                    overflow="visible"
                    className="block"
                    role="group"
                    aria-label={`Map of ${counts.notes} notes`}
                  >
                    {halos}
                    {edgeLayers.under}
                    {nodeLayer}
                    {edgeLayers.lit}
                    {selectedLayer}
                  </svg>
                </div>

                <div className="pointer-events-none absolute inset-0" aria-hidden>
                  {layout.clusters.map((c) => {
                    const p = toScreen(c.cx, c.cy - c.r);
                    if (!onScreen(p, 120)) return null;
                    const dim = folderFilter && c.key !== folderFilter;
                    return (
                      <span
                        key={c.key}
                        className="absolute -translate-x-1/2 whitespace-nowrap text-[11px] font-semibold uppercase tracking-[0.08em]"
                        style={{
                          left: p.left,
                          top: p.top + 10,
                          color: clusterColor(c.key),
                          opacity: dim ? 0.3 : 0.85,
                        }}
                      >
                        {c.label}
                      </span>
                    );
                  })}
                  {labelIds.map((id) => {
                    const n = byId.get(id);
                    if (!n) return null;
                    const isSel = id === selectedId;
                    const rScreen = (n.r + (isSel ? 2 : 0)) * ns * cam.k;
                    const p = toScreen(n.x, n.y);
                    if (!onScreen(p)) return null;
                    const dim = !isSel && !inFilter(n.cluster);
                    return (
                      <span
                        key={id}
                        className={`absolute line-clamp-2 w-max max-w-[180px] -translate-x-1/2 rounded-[8px] px-2 py-[3px] text-center text-[12px] font-medium leading-[1.3] ${
                          isSel
                            ? "z-10 bg-accent text-accent-ink"
                            : "border border-button bg-surface text-primary"
                        }`}
                        style={{
                          left: p.left,
                          top: p.top + rScreen + (isSel ? 10 : 6),
                          opacity: dim ? 0.2 : 1,
                        }}
                      >
                        {layout.labels[id] ?? id}
                      </span>
                    );
                  })}
                </div>
              </>
            )
          )}

          <p className="pointer-events-none absolute bottom-3 left-3 inline-flex h-8 items-center rounded-chip border border-control bg-surface/90 px-3 text-[12px] text-tertiary max-[520px]:hidden">
            Drag to pan · scroll to zoom · click a dot
          </p>
          <div className="absolute bottom-3 right-3 flex flex-col overflow-hidden rounded-button border border-control bg-surface">
            <button
              type="button"
              aria-label="Zoom in"
              onClick={() => zoomButton(1.3)}
              className="flex h-11 w-11 items-center justify-center text-secondary hover:bg-hover hover:text-primary"
            >
              <Plus aria-hidden className="h-[18px] w-[18px]" strokeWidth={1.75} />
            </button>
            <button
              type="button"
              aria-label="Zoom out"
              onClick={() => zoomButton(1 / 1.3)}
              className="flex h-11 w-11 items-center justify-center border-y border-control text-secondary hover:bg-hover hover:text-primary"
            >
              <Minus aria-hidden className="h-[18px] w-[18px]" strokeWidth={1.75} />
            </button>
            <button
              type="button"
              aria-label="Fit map to view"
              onClick={() => size && setCam(fitCamera(layout, size.w, size.h))}
              className="flex h-11 w-11 items-center justify-center text-secondary hover:bg-hover hover:text-primary"
            >
              <Maximize2 aria-hidden className="h-4 w-4" strokeWidth={1.75} />
            </button>
          </div>
        </div>

        {/* The inspector matches the graph panel's height and scrolls inside;
            under 800px it stacks below the graph at its natural height. */}
        <div className="relative w-[300px] shrink-0 max-[800px]:w-full">
          <div className="absolute inset-0 flex max-[800px]:static">
            {selected ? (
              <MapInspector
                id={selected.id}
                title={layout.labels[selected.id] ?? selected.id}
                folder={selected.chat ? "Chat" : selected.cluster}
                color={selected.chat ? CHAT_COLOR : clusterColor(selected.cluster)}
                linkedNotes={inspectorNeighbors.filter((n) => !n.chat).length}
                neighbors={inspectorNeighbors}
                onSelect={(id) => selectNote(id)}
                onOpen={() => selectNote(selected.id, { view: "notes" })}
                onAsk={() => selectNote(selected.id, { view: "ask", askContext: true })}
              />
            ) : (
              <aside
                aria-label="Selected note"
                className="flex w-full flex-1 items-center justify-center rounded-card border border-divider bg-panel p-5 text-center text-[14px] text-tertiary"
              >
                {graphStatus === "ok" ? "Click a dot to see its links." : "Nothing selected."}
              </aside>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function FilterChip({
  label,
  color,
  active,
  onClick,
}: {
  label: string;
  color?: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`inline-flex h-9 items-center gap-2 rounded-chip border px-3.5 text-[13px] font-medium transition-colors ${
        active
          ? "border-strong bg-chip-active text-primary"
          : "border-control text-secondary hover:border-strong hover:text-primary"
      }`}
    >
      {color && (
        <span aria-hidden className="h-2 w-2 rounded-full" style={{ background: color }} />
      )}
      {label}
    </button>
  );
}
