"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { CircleAlert, Minus, Orbit, Pause, Play, Plus, RotateCcw, Scan } from "lucide-react";
import { GLOBE_COLORS, SHOW_ALL, pointFor, type Globe, type GlobeFilter } from "@/lib/vaultGlobe";
import { createGlobeEngine, type GlobeEngine } from "./globeEngine";

export type GlobeState = "loading" | "ready" | "error";

type Phase = "starting" | "ready" | "no-webgl" | "failed";

const NO_SOURCES: ReadonlySet<string> = new Set();
/** Each zoom button press moves the camera this much closer or farther. */
const ZOOM_STEP = 1.25;

function hasWebGL(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") || canvas.getContext("webgl"));
  } catch {
    return false;
  }
}

/**
 * The 3D map of the whole vault: every note and AI chat is a dot. It turns
 * slowly until someone clicks or scrolls on it. The three.js code loads only
 * in the browser, on first use.
 */
export function VaultGlobe({
  globe,
  state,
  errorText,
  selectedId,
  turnToId,
  sourceIds = NO_SOURCES,
  filter = SHOW_ALL,
  query = "",
  onPick,
  head,
  className = "",
  label,
}: {
  globe: Globe | null;
  state: GlobeState;
  errorText?: string;
  /** The open note: drawn white with a ring and its name. */
  selectedId: string | null;
  /** When this changes, the camera turns to face that note (the first value only marks it). */
  turnToId: string | null;
  /** Sources of the latest answer, marked with a bracket. */
  sourceIds?: ReadonlySet<string>;
  filter?: GlobeFilter;
  query?: string;
  onPick: (id: string) => void;
  /** Shown in the top-left corner of the map. */
  head?: ReactNode;
  className?: string;
  label: string;
}) {
  const mountRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<GlobeEngine | null>(null);
  const onPickRef = useRef(onPick);
  const turnedRef = useRef<string | null | undefined>(undefined);
  const [phase, setPhase] = useState<Phase>("starting");
  const [spinning, setSpinning] = useState(true);

  useEffect(() => {
    onPickRef.current = onPick;
  }, [onPick]);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    let cancelled = false;
    let engine: GlobeEngine | null = null;
    (async () => {
      try {
        const [graphLib, THREE, bloomLib, outputLib] = await Promise.all([
          import("3d-force-graph"),
          import("three"),
          import("three/examples/jsm/postprocessing/UnrealBloomPass.js"),
          import("three/examples/jsm/postprocessing/OutputPass.js"),
        ]);
        await document.fonts.ready;
        if (cancelled) return;
        if (!hasWebGL()) {
          setPhase("no-webgl");
          return;
        }
        const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        engine = createGlobeEngine(
          mount,
          {
            ForceGraph3D: graphLib.default,
            THREE,
            UnrealBloomPass: bloomLib.UnrealBloomPass,
            OutputPass: outputLib.OutputPass,
          },
          { onPick: (id) => onPickRef.current(id), onSpinStopped: () => setSpinning(false) },
          { reducedMotion },
        );
        engineRef.current = engine;
        if (reducedMotion) setSpinning(false);
        setPhase("ready");
      } catch (err) {
        console.error("The 3D map could not start.", err);
        if (!cancelled) setPhase("failed");
      }
    })();
    return () => {
      cancelled = true;
      engineRef.current = null;
      engine?.dispose();
    };
  }, []);

  useEffect(() => {
    if (phase === "ready" && globe) engineRef.current?.setData(globe);
  }, [phase, globe]);

  const selectedPoint = globe && selectedId ? pointFor(globe, selectedId) : null;
  useEffect(() => {
    if (phase !== "ready" || !globe) return;
    const sources = new Set([...sourceIds].map((id) => pointFor(globe, id)));
    engineRef.current?.setView({ selected: selectedPoint, sources, filter, query });
  }, [phase, globe, selectedPoint, sourceIds, filter, query]);

  const turnPoint = globe && turnToId ? pointFor(globe, turnToId) : null;
  useEffect(() => {
    if (phase !== "ready" || !globe) return;
    // The note that is already open when the map appears is marked, not flown to.
    if (turnedRef.current !== undefined && turnPoint && turnPoint !== turnedRef.current) {
      engineRef.current?.turnTo(turnPoint);
    }
    turnedRef.current = turnPoint;
  }, [phase, globe, turnPoint]);

  useEffect(() => {
    if (phase === "ready") engineRef.current?.setSpin(spinning);
  }, [phase, spinning]);

  const notes = globe ? globe.counts.chats + globe.counts.notes : 0;
  const message =
    phase === "no-webgl"
      ? { problem: true, title: "The 3D map needs WebGL.", text: "Turn on hardware acceleration in your browser, or use the Recent list and Ctrl K search." }
      : phase === "failed"
        ? { problem: true, title: "The map could not start.", text: "Reload the page. Nothing in your vault was changed." }
        : state === "error"
          ? { problem: true, title: "The map could not load.", text: errorText || "Start the backend, then reload. Nothing in your vault was changed." }
          : state === "ready" && globe && notes === 0
            ? { problem: false, title: "No dots yet.", text: "Notes appear here once the index has scanned your vault." }
            : null;
  const loading = !message && (phase === "starting" || state === "loading");

  return (
    <section className={`globe ${className}`} aria-label={label} aria-busy={loading || undefined}>
      <div ref={mountRef} className="globe-canvas" />
      {head && <div className="sky-head">{head}</div>}
      {phase === "ready" && state === "ready" && notes > 0 && (
        <div className="globe-tools">
          <button type="button" className="btn" onClick={() => setSpinning((on) => !on)}>
            {spinning ? <Pause className="icon" aria-hidden strokeWidth={2} /> : <Play className="icon" aria-hidden strokeWidth={2} />}
            {spinning ? "Stop spinning" : "Spin"}
          </button>
          <button type="button" className="btn btn-icon" aria-label="Zoom in" title="Zoom in" onClick={() => engineRef.current?.zoom(1 / ZOOM_STEP)}>
            <Plus className="icon" aria-hidden strokeWidth={2} />
          </button>
          <button type="button" className="btn btn-icon" aria-label="Zoom out" title="Zoom out" onClick={() => engineRef.current?.zoom(ZOOM_STEP)}>
            <Minus className="icon" aria-hidden strokeWidth={2} />
          </button>
          <button type="button" className="btn" onClick={() => engineRef.current?.reset()}>
            <RotateCcw className="icon" aria-hidden strokeWidth={2} />
            Reset view
          </button>
        </div>
      )}
      {loading && (
        <p className="sky-msg mono" role="status">
          Loading map…
        </p>
      )}
      {message && (
        <div className={`sky-msg${message.problem ? " is-error" : ""}`} role={message.problem ? "alert" : undefined}>
          {message.problem ? <CircleAlert aria-hidden strokeWidth={2} /> : <Orbit aria-hidden strokeWidth={2} />}
          <strong>{message.title}</strong>
          <p>{message.text}</p>
        </div>
      )}
    </section>
  );
}

/** How to read the map, in plain words. */
export function GlobeLegend({ showSource }: { showSource: boolean }) {
  return (
    <ul className="legend mono" aria-label="How to read the map">
      <li>
        <span className="key">
          <span className="dot" style={{ width: 8, height: 8, background: GLOBE_COLORS.chat }} />
        </span>
        AI chat
      </li>
      <li>
        <span className="key">
          <span className="dot" style={{ width: 8, height: 8, background: GLOBE_COLORS.note }} />
        </span>
        Note
      </li>
      <li>
        <span className="key">
          <span className="dot" style={{ width: 12, height: 12 }} />
        </span>
        Folder (its dots gather around it)
      </li>
      <li>
        <span className="key">
          <span className="line" />
        </span>
        Line = one note links to the other
      </li>
      {showSource && (
        <li>
          <span className="key">
            <Scan className="icon" aria-hidden strokeWidth={2} />
          </span>
          Source of the latest answer
        </li>
      )}
      <li className="hint">Click a dot to open it · drag to turn · scroll to zoom</li>
    </ul>
  );
}
