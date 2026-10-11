/**
 * Star-chart layout for the Notes view. Pure calculations: notes in, positions out.
 *
 * Coordinates are percentages of one square plot box (0..100 on both axes,
 * center at 50,50). Stars, star labels, ring labels and the ring circles all
 * use this one coordinate system, so a star always sits between the right
 * age rings whatever size the box is drawn at.
 *
 * - Distance from the center = time since the last edit, on a square-root
 *   scale. The age rings use the same scale (`radiusFor`).
 * - Every star is the same size. Size would need each note's full text, and
 *   reading every recent note (OneDrive may download it) is not worth that.
 * - Constellation = folder, by the app's own `folderCluster()`. With more than
 *   one folder, each folder gets its own wedge of the circle.
 * - Lines = links between two plotted notes in the graph data. No link, no line.
 * - The angle inside a constellation only keeps stars apart; it means nothing.
 */
import { folderCluster } from "./graphLayout";

export const DAY_MS = 86_400_000;

/** Radius of the newest and oldest possible star, as a fraction of the box side. */
export const R_MIN = 0.13;
export const R_MAX = 0.42;

const GOLDEN = 0.381966; // 137.5 degrees as a fraction of a turn
const START_DEG = -30;
const WEDGE_GAP_DEG = 14;
const LABEL_CHAR_PCT = 2.2;
const LABEL_H_PCT = 6;
const MAX_LABEL_CHARS = 22;

/** Ring ages the chart can draw, shortest first. The chart shows the last three that fit. */
export const RING_LADDER: readonly { days: number; label: string }[] = [
  { days: 5 / 1440, label: "5 min" },
  { days: 15 / 1440, label: "15 min" },
  { days: 1 / 24, label: "1 hour" },
  { days: 6 / 24, label: "6 hours" },
  { days: 1, label: "1 day" },
  { days: 7, label: "1 week" },
  { days: 14, label: "2 weeks" },
  { days: 30, label: "1 month" },
  { days: 91, label: "3 months" },
  { days: 365, label: "1 year" },
  { days: 730, label: "2 years" },
];

export type ChartNote = Readonly<{
  id: string;
  title: string;
  /** last edit, epoch milliseconds */
  editedMs: number;
}>;

export type ChartLink = Readonly<{ source: string; target: string; is_ghost?: boolean }>;

export type LabelSide = "right" | "left" | "below" | "above";

export type Star = Readonly<{
  id: string;
  title: string;
  /** shortened title for the on-chart label */
  label: string;
  folder: string;
  ageDays: number;
  x: number;
  y: number;
  /** distance from the center, in percent of the box side */
  r: number;
  side: LabelSide;
}>;

export type AgeRing = Readonly<{
  days: number;
  label: string;
  /** radius in percent of the box side */
  r: number;
  /** where the ring's label sits (percent) */
  x: number;
  y: number;
}>;

export type Constellation = Readonly<{
  folder: string;
  count: number;
  /** label position (percent), only meaningful when there is more than one */
  x: number;
  y: number;
}>;

export type ChartLine = Readonly<{ source: string; target: string; x1: number; y1: number; x2: number; y2: number }>;

export type StarChart = Readonly<{
  maxDays: number;
  stars: Star[];
  rings: AgeRing[];
  constellations: Constellation[];
  lines: ChartLine[];
}>;

type Box = { x0: number; x1: number; y0: number; y1: number };

export function ageDays(editedMs: number, nowMs: number): number {
  return Math.max(0, (nowMs - editedMs) / DAY_MS);
}

/** The scale's outer edge: a little past the oldest note, never under one hour. */
export function scaleMaxDays(ages: readonly number[]): number {
  const oldest = ages.length ? Math.max(...ages) : 0;
  return Math.max(oldest * 1.07, 1 / 24);
}

/** Distance from the center (fraction of the box side) for an age. Same scale for stars and rings. */
export function radiusFor(days: number, maxDays: number): number {
  const t = Math.min(Math.max(days, 0), maxDays) / maxDays;
  return R_MIN + (R_MAX - R_MIN) * Math.sqrt(t);
}

/** The last three ring ages that fall inside the scale. */
export function ringAges(maxDays: number): { days: number; label: string }[] {
  return RING_LADDER.filter((g) => g.days < maxDays).slice(-3);
}

export function pointAt(r: number, deg: number): { x: number; y: number } {
  const rad = (deg * Math.PI) / 180;
  return { x: 50 + 100 * r * Math.cos(rad), y: 50 + 100 * r * Math.sin(rad) };
}

export function shortLabel(title: string): string {
  return title.length <= MAX_LABEL_CHARS ? title : `${title.slice(0, MAX_LABEL_CHARS - 1).trimEnd()}…`;
}

function frac(v: number): number {
  return v - Math.floor(v);
}

/**
 * Folders in recency order of their newest note, each with its wedge of the
 * circle (degrees). One folder takes the whole circle.
 */
function wedges(folders: string[], counts: Map<string, number>, total: number) {
  if (folders.length <= 1) {
    return new Map(folders.map((f) => [f, { a0: START_DEG, span: 360, full: true }]));
  }
  const usable = 360 - WEDGE_GAP_DEG * folders.length;
  let a = START_DEG;
  const out = new Map<string, { a0: number; span: number; full: boolean }>();
  for (const f of folders) {
    const span = (usable * (counts.get(f) || 0)) / total;
    out.set(f, { a0: a + WEDGE_GAP_DEG / 2, span, full: false });
    a += span + WEDGE_GAP_DEG;
  }
  return out;
}

function boxGap(a: Box, b: Box): number {
  return Math.max(a.x0 - b.x1, b.x0 - a.x1, a.y0 - b.y1, b.y0 - a.y1);
}

function inside(b: Box): boolean {
  return b.x0 >= 1 && b.x1 <= 99 && b.y0 >= 1 && b.y1 <= 99;
}

function labelBox(p: { x: number; y: number }, w: number, side: LabelSide): Box {
  const h = LABEL_H_PCT;
  switch (side) {
    case "right":
      return { x0: p.x + 2, x1: p.x + 2 + w, y0: p.y - h / 2, y1: p.y + h / 2 };
    case "left":
      return { x0: p.x - 2 - w, x1: p.x - 2, y0: p.y - h / 2, y1: p.y + h / 2 };
    case "below":
      return { x0: p.x - w / 2, x1: p.x + w / 2, y0: p.y + 2, y1: p.y + 2 + h };
    case "above":
      return { x0: p.x - w / 2, x1: p.x + w / 2, y0: p.y - 2 - h, y1: p.y - 2 };
  }
}

function dotBox(p: { x: number; y: number }, half: number): Box {
  return { x0: p.x - half, x1: p.x + half, y0: p.y - half, y1: p.y + half };
}

/** Greedy label placement: each label takes the side with the most room from what is already placed. */
function placeLabels(points: { x: number; y: number; label: string }[], fixed: Box[]) {
  const dots = points.map((p) => dotBox(p, 1.5));
  const center: Box = { x0: 47, x1: 53, y0: 47, y1: 53 };
  const sides: LabelSide[] = [];
  const boxes: Box[] = [];
  points.forEach((p, i) => {
    const w = p.label.length * LABEL_CHAR_PCT;
    const others = [center, ...fixed, ...dots.filter((_, j) => j !== i), ...boxes];
    let best: { side: LabelSide; b: Box; score: number } | null = null;
    for (const side of ["right", "left", "below", "above"] as const) {
      const b = labelBox(p, w, side);
      const score = inside(b) ? Math.min(...others.map((o) => boxGap(b, o))) : -Infinity;
      if (!best || score > best.score) best = { side, b, score };
    }
    sides.push(best!.side);
    boxes.push(best!.b);
  });
  return { sides, boxes };
}

const RING_LABEL_ANGLES = [45, 135, -45, -135, 90, -90, 0, 180, 22.5, 67.5, 112.5, 157.5, -22.5, -67.5, -112.5, -157.5];

/** Each ring label takes the spot on its ring with the most room from everything placed before it. */
function placeRingLabels(rings: { days: number; label: string }[], maxDays: number, taken: Box[]): AgeRing[] {
  const placed: { ring: AgeRing; b: Box }[] = [];
  for (const g of rings) {
    const r = radiusFor(g.days, maxDays);
    let best: { ring: AgeRing; b: Box; score: number } | null = null;
    for (const deg of RING_LABEL_ANGLES) {
      const p = pointAt(r, deg);
      const b: Box = { x0: p.x, x1: p.x + 3 + g.label.length * LABEL_CHAR_PCT, y0: p.y - LABEL_H_PCT / 2, y1: p.y + LABEL_H_PCT / 2 };
      const others = [...taken, ...placed.map((q) => q.b)];
      const score = inside(b) ? Math.min(Infinity, ...others.map((o) => boxGap(b, o))) : -Infinity;
      if (!best || score > best.score) best = { ring: { days: g.days, label: g.label, r: r * 100, x: p.x, y: p.y }, b, score };
    }
    placed.push({ ring: best!.ring, b: best!.b });
  }
  return placed.map((q) => q.ring);
}

/**
 * Lay out the chart. `notes` should be newest first (the order /api/recent
 * returns); `links` is the vault graph's edge list, of which only links
 * between two plotted notes are drawn.
 */
export function layoutStarChart(
  notes: readonly ChartNote[],
  links: readonly ChartLink[],
  nowMs: number,
): StarChart {
  const ages = notes.map((n) => ageDays(n.editedMs, nowMs));
  const maxDays = scaleMaxDays(ages);

  const folderOf = notes.map((n) => folderCluster(n.id));
  const folders = [...new Set(folderOf)];
  const counts = new Map<string, number>();
  folderOf.forEach((f) => counts.set(f, (counts.get(f) || 0) + 1));
  const wedge = wedges(folders, counts, notes.length);


  const seen = new Map<string, number>();
  const points = notes.map((n, i) => {
    const f = folderOf[i];
    const k = seen.get(f) || 0;
    seen.set(f, k + 1);
    const w = wedge.get(f)!;
    const deg = w.full ? w.a0 + 360 * frac(k * GOLDEN) : w.a0 + w.span * (0.12 + 0.76 * frac(k * GOLDEN));
    const r = radiusFor(ages[i], maxDays);
    return { ...pointAt(r, deg), r, label: shortLabel(n.title) };
  });

  const constellations: Constellation[] = folders.map((f) => {
    const w = wedge.get(f)!;
    const p = pointAt(R_MAX + 0.05, w.a0 + w.span / 2);
    const half = (f.length * LABEL_CHAR_PCT) / 2;
    return {
      folder: f,
      count: counts.get(f) || 0,
      x: Math.min(99 - half, Math.max(1 + half, p.x)),
      y: Math.min(97, Math.max(3, p.y)),
    };
  });
  const constellationBoxes: Box[] =
    folders.length > 1
      ? constellations.map((c) => {
          const half = (c.folder.length * LABEL_CHAR_PCT) / 2;
          return { x0: c.x - half, x1: c.x + half, y0: c.y - LABEL_H_PCT / 2, y1: c.y + LABEL_H_PCT / 2 };
        })
      : [];

  const { sides, boxes } = placeLabels(points, constellationBoxes);

  const stars: Star[] = notes.map((n, i) => ({
    id: n.id,
    title: n.title,
    label: points[i].label,
    folder: folderOf[i],
    ageDays: ages[i],
    x: points[i].x,
    y: points[i].y,
    r: points[i].r * 100,
    side: sides[i],
  }));

  const taken = [...boxes, ...constellationBoxes, ...points.map((p) => dotBox(p, 2))];
  // No notes, no scale: rings would only describe an empty sky.
  const rings = notes.length ? placeRingLabels(ringAges(maxDays), maxDays, taken) : [];

  const byId = new Map(stars.map((s) => [s.id, s]));
  const lines: ChartLine[] = [];
  const drawn = new Set<string>();
  for (const e of links) {
    if (e.is_ghost || e.source === e.target) continue;
    const a = byId.get(e.source);
    const b = byId.get(e.target);
    if (!a || !b) continue;
    const key = [a.id, b.id].sort().join("\0");
    if (drawn.has(key)) continue;
    drawn.add(key);
    lines.push({ source: a.id, target: b.id, x1: a.x, y1: a.y, x2: b.x, y2: b.y });
  }

  return { maxDays, stars, rings, constellations, lines };
}

/** A seeded background field of faint dots: the same sky every time. Decoration only. */
export function starField(seed: number, count: number): { x: number; y: number; r: number }[] {
  const out: { x: number; y: number; r: number }[] = [];
  let s = seed >>> 0;
  const next = () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
  for (let i = 0; i < count; i++) out.push({ x: next() * 1000, y: next() * 600, r: 0.6 + next() * 1.1 });
  return out;
}
