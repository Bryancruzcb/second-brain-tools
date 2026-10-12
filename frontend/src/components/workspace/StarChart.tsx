"use client";

import { CircleAlert, List, Orbit, Scan } from "lucide-react";
import { relativeDay } from "@/lib/format";
import { starField, type StarChart as Chart } from "@/lib/starChart";

const FIELD = starField(20261011, 150);
/** Every star is one size: the chart encodes edit time, folder and links, not length. */
const STAR_PX = 7;

export type ChartState = "loading" | "ready" | "empty" | "error";

/**
 * The star chart of recent notes. Layout comes from lib/starChart (pure);
 * this component only draws it. Every position is a percentage of the square
 * `.plot` box, the same box the ring circles are drawn in.
 */
export function StarChart({
  state,
  chart,
  editedIso,
  selectedId,
  sourceIds,
  onSelect,
  nowMs,
}: {
  state: ChartState;
  chart: Chart;
  editedIso: Record<string, string>;
  selectedId: string | null;
  sourceIds: ReadonlySet<string>;
  onSelect: (id: string) => void;
  nowMs: number;
}) {
  const ready = state === "ready";
  const folders = chart.constellations;
  const head = ready
    ? folders.length === 1
      ? (
          <>
            Constellation <b>{folders[0].folder}</b> · <span className="num">{chart.stars.length}</span>{" "}
            {chart.stars.length === 1 ? "star" : "stars"}
          </>
        )
      : (
          <>
            <span className="num">{folders.length}</span> constellations · <span className="num">{chart.stars.length}</span> stars
          </>
        )
    : "Star chart";

  return (
    <section className="sky" aria-label="Star chart of your recent notes" aria-busy={state === "loading" || undefined}>
      <svg className="field" viewBox="0 0 1000 600" preserveAspectRatio="xMidYMid slice" aria-hidden>
        {FIELD.map((p, i) => (
          <circle key={i} cx={p.x.toFixed(1)} cy={p.y.toFixed(1)} r={p.r.toFixed(2)} />
        ))}
      </svg>
      <div className="sky-head">
        <p className="constellation-count mono">{head}</p>
        <a className="to-list" href="#recent">
          <List className="icon" aria-hidden strokeWidth={2} />
          List view
        </a>
      </div>
      <div className="plot">
        <svg className="rings" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
          {chart.rings.map((g) => (
            <circle key={g.label} cx="50" cy="50" r={g.r.toFixed(3)} />
          ))}
          {ready &&
            chart.lines.map((l) => (
              <line key={`${l.source}\0${l.target}`} className="link" x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2} />
            ))}
          <line className="cross" x1="48.6" y1="50" x2="51.4" y2="50" />
          <line className="cross" x1="50" y1="48.6" x2="50" y2="51.4" />
        </svg>
        {state !== "loading" && (
          <>
            {chart.rings.map((g) => (
              <span key={g.label} className="ring-label mono" style={{ left: `${g.x.toFixed(2)}%`, top: `${g.y.toFixed(2)}%` }}>
                {g.label}
              </span>
            ))}
            <span className="now-label mono">now</span>
          </>
        )}
        {ready && folders.length > 1 &&
          folders.map((c) => (
            <span
              key={c.folder}
              className="constellation-label mono"
              style={{ left: `${c.x.toFixed(2)}%`, top: `${c.y.toFixed(2)}%` }}
              aria-hidden
            >
              {c.folder}
            </span>
          ))}
        {ready &&
          chart.stars.map((s) => {
            const isSource = sourceIds.has(s.id);
            const edited = editedIso[s.id];
            const parts = [
              s.title,
              `in ${s.folder}`,
              edited ? `edited ${relativeDay(edited, nowMs).toLowerCase()}` : null,
              isSource ? "source of the latest answer" : null,
            ].filter(Boolean);
            return (
              <div key={s.id} className="anchor" style={{ left: `${s.x.toFixed(3)}%`, top: `${s.y.toFixed(3)}%` }}>
                {isSource && (
                  <span className="reticle lock" aria-hidden>
                    <Scan strokeWidth={1.5} />
                  </span>
                )}
                <button
                  type="button"
                  className="star"
                  data-side={s.side}
                  aria-pressed={s.id === selectedId}
                  aria-label={parts.join(", ")}
                  title={s.title}
                  onClick={() => onSelect(s.id)}
                >
                  <span className="dotbox">
                    <span className="dot" style={{ width: STAR_PX, height: STAR_PX }} />
                  </span>
                  <span className="star-name mono" aria-hidden>
                    {s.label}
                  </span>
                </button>
              </div>
            );
          })}
      </div>
      {state === "empty" && (
        <div className="sky-msg">
          <Orbit aria-hidden strokeWidth={2} />
          <strong>No stars yet.</strong>
          <p>Notes appear here once the index has scanned your vault.</p>
        </div>
      )}
      {state === "error" && (
        <div className="sky-msg is-error" role="alert">
          <CircleAlert aria-hidden strokeWidth={2} />
          <strong>The chart could not load.</strong>
          <p>Start the backend, then reload. Nothing in your vault was changed.</p>
        </div>
      )}
    </section>
  );
}

/** How to read the chart. Each line is only shown when it is true of what is drawn. */
export function ChartLegend({
  chart,
  linksKnown,
  sourceOnChart,
}: {
  chart: Chart;
  linksKnown: boolean;
  sourceOnChart: boolean;
}) {
  return (
    <ul className="legend mono" aria-label="How to read the chart">
      <li>
        <span className="key">
          <span className="dot" style={{ width: 6, height: 6 }} />
        </span>
        Closer to the center = edited more recently
      </li>
      {chart.constellations.length > 1 && <li>Constellation = folder</li>}
      {sourceOnChart && (
        <li>
          <span className="key">
            <Scan className="icon" aria-hidden strokeWidth={2} />
          </span>
          Source of the latest answer
        </li>
      )}
      {linksKnown && chart.lines.length > 0 && (
        <li>
          <span className="key">
            <span className="line" />
          </span>
          Line = one note links to the other
        </li>
      )}
    </ul>
  );
}
