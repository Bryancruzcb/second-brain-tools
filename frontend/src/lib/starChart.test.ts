import { describe, expect, test } from "bun:test";
import {
  DAY_MS,
  R_MAX,
  R_MIN,
  layoutStarChart,
  radiusFor,
  ringAges,
  scaleMaxDays,
  shortLabel,
  starField,
  type ChartNote,
} from "./starChart";

// The six public fixture notes with the edit times round 1 picked (PDT, 2026),
// and "now" fixed at 2026-10-11 11:40 PDT.
const NOW = Date.parse("2026-10-11T11:40:00-07:00");
const FIXTURE: ChartNote[] = [
  { id: "Sourdough Starter.md", title: "Sourdough Starter", editedMs: 1791733200_000 },
  { id: "Levain.md", title: "Levain", editedMs: 1791648300_000 },
  { id: "Rust Borrow Checker.md", title: "Rust Borrow Checker", editedMs: 1791513000_000 },
  { id: "Track Intervals.md", title: "Track Intervals", editedMs: 1791296100_000 },
  { id: "Coffee Brewing.md", title: "Coffee Brewing", editedMs: 1790910600_000 },
  { id: "Marathon Training.md", title: "Marathon Training", editedMs: 1790430600_000 },
];

function distance(s: { x: number; y: number }): number {
  return Math.hypot(s.x - 50, s.y - 50);
}

/** The bug check from round 2: a star must sit inside exactly the rings that are older than it. */
function expectStarsBetweenTheirRings(notes: ChartNote[], nowMs: number) {
  const chart = layoutStarChart(notes, [], nowMs);
  for (const star of chart.stars) {
    const d = distance(star);
    // The drawn position and the reported radius agree (one coordinate system).
    expect(Math.abs(d - star.r)).toBeLessThan(1e-9);
    for (const ring of chart.rings) {
      if (star.ageDays < ring.days) expect(d).toBeLessThan(ring.r);
      else expect(d).toBeGreaterThanOrEqual(ring.r - 1e-9);
    }
  }
  return chart;
}

describe("star chart scale", () => {
  test("rings and stars share one radius scale that grows with age", () => {
    const max = 16;
    expect(radiusFor(0, max)).toBe(R_MIN);
    expect(radiusFor(max, max)).toBe(R_MAX);
    expect(radiusFor(99, max)).toBe(R_MAX);
    for (let d = 0; d < max; d += 0.25) {
      expect(radiusFor(d + 0.25, max)).toBeGreaterThan(radiusFor(d, max));
    }
  });

  test("shows the three largest ring ages inside the scale", () => {
    expect(ringAges(16.3).map((r) => r.label)).toEqual(["1 day", "1 week", "2 weeks"]);
    expect(ringAges(0.5).map((r) => r.label)).toEqual(["15 min", "1 hour", "6 hours"]);
    expect(ringAges(400).map((r) => r.label)).toEqual(["1 month", "3 months", "1 year"]);
    expect(scaleMaxDays([])).toBeCloseTo(1 / 24);
  });
});

describe("layoutStarChart", () => {
  test("every fixture star sits between the correct age rings", () => {
    const chart = expectStarsBetweenTheirRings(FIXTURE, NOW);
    expect(chart.rings.map((r) => r.label)).toEqual(["1 day", "1 week", "2 weeks"]);
    const band = (id: string) => {
      const s = chart.stars.find((x) => x.id === id)!;
      return chart.rings.filter((r) => distance(s) > r.r).length;
    };
    // 0 = inside 1 day, 1 = 1 day to 1 week, 2 = 1 to 2 weeks, 3 = over 2 weeks
    expect(band("Sourdough Starter.md")).toBe(0);
    expect(band("Levain.md")).toBe(1);
    expect(band("Rust Borrow Checker.md")).toBe(1);
    expect(band("Track Intervals.md")).toBe(1);
    expect(band("Coffee Brewing.md")).toBe(2);
    expect(band("Marathon Training.md")).toBe(3);
  });

  test("stars stay between their rings for many random vaults", () => {
    let seed = 7;
    const rand = () => {
      seed = (Math.imul(seed, 1103515245) + 12345) >>> 0;
      return seed / 4294967296;
    };
    const folders = ["", "00 Home/", "02 Projects/", "03 School/", "05 AI Chats/"];
    for (let trial = 0; trial < 200; trial++) {
      const scaleDays = [0.01, 0.3, 3, 20, 120, 900][trial % 6];
      const notes: ChartNote[] = Array.from({ length: 1 + Math.floor(rand() * 8) }, (_, i) => ({
        id: `${folders[Math.floor(rand() * folders.length)]}Note ${i}.md`,
        title: `Note ${i}`,
        editedMs: NOW - rand() * scaleDays * DAY_MS,
      })).sort((a, b) => b.editedMs - a.editedMs);
      expectStarsBetweenTheirRings(notes, NOW);
    }
  });

  test("a note edited exactly on a ring age sits on that ring, not inside it", () => {
    const notes: ChartNote[] = [
      { id: "a.md", title: "A", editedMs: NOW - 0.5 * DAY_MS },
      { id: "b.md", title: "B", editedMs: NOW - 7 * DAY_MS },
      { id: "c.md", title: "C", editedMs: NOW - 15 * DAY_MS },
    ];
    const chart = expectStarsBetweenTheirRings(notes, NOW);
    const week = chart.rings.find((r) => r.label === "1 week")!;
    expect(distance(chart.stars[1])).toBeCloseTo(week.r, 9);
  });

  test("labels, stars and ring labels stay inside the plot box", () => {
    const chart = layoutStarChart(FIXTURE, [], NOW);
    for (const s of chart.stars) {
      expect(s.x).toBeGreaterThan(0);
      expect(s.x).toBeLessThan(100);
      expect(s.y).toBeGreaterThan(0);
      expect(s.y).toBeLessThan(100);
    }
    for (const r of chart.rings) {
      expect(Math.hypot(r.x - 50, r.y - 50)).toBeCloseTo(r.r, 9);
    }
  });

  test("one folder is one constellation, named by folderCluster", () => {
    const chart = layoutStarChart(FIXTURE, [], NOW);
    expect(chart.constellations.map((c) => [c.folder, c.count])).toEqual([["Vault", 6]]);
    expect(new Set(chart.stars.map((s) => s.folder))).toEqual(new Set(["Vault"]));
  });

  test("each folder gets its own wedge of the circle", () => {
    const notes: ChartNote[] = [
      { id: "03 School/Graphs.md", title: "Graphs", editedMs: NOW - 1000 },
      { id: "02 Projects/Atlas.md", title: "Atlas", editedMs: NOW - 2 * DAY_MS },
      { id: "03 School/Heaps.md", title: "Heaps", editedMs: NOW - 3 * DAY_MS },
      { id: "02 Projects/Gridiron.md", title: "Gridiron", editedMs: NOW - 4 * DAY_MS },
    ];
    const chart = layoutStarChart(notes, [], NOW);
    expect(chart.constellations.map((c) => c.folder)).toEqual(["School", "Projects"]);
    const angle = (id: string) => {
      const s = chart.stars.find((x) => x.id === id)!;
      return Math.atan2(s.y - 50, s.x - 50);
    };
    const school = [angle("03 School/Graphs.md"), angle("03 School/Heaps.md")];
    const projects = [angle("02 Projects/Atlas.md"), angle("02 Projects/Gridiron.md")];
    // The wedges are separate: the two folders' angle ranges do not interleave.
    const unwrap = (a: number) => (a < -Math.PI / 6 - 1e-9 ? a + 2 * Math.PI : a);
    const [s0, s1] = school.map(unwrap).sort((a, b) => a - b);
    const [p0, p1] = projects.map(unwrap).sort((a, b) => a - b);
    expect(s1 < p0 || p1 < s0).toBe(true);
  });

  test("draws a line only for a real link between two plotted notes", () => {
    const links = [
      { source: "Levain.md", target: "Sourdough Starter.md" },
      { source: "Sourdough Starter.md", target: "Levain.md" },
      { source: "Levain.md", target: "Not Plotted.md" },
      { source: "Coffee Brewing.md", target: "Marathon Training.md", is_ghost: true },
    ];
    const chart = layoutStarChart(FIXTURE, links, NOW);
    expect(chart.lines.map((l) => [l.source, l.target])).toEqual([["Levain.md", "Sourdough Starter.md"]]);
    expect(layoutStarChart(FIXTURE, [], NOW).lines).toEqual([]);
  });

  test("needs only id, title and edit time: no note text, so no note reads", () => {
    const chart = layoutStarChart(FIXTURE, [], NOW);
    expect(Object.keys(chart.stars[0]).sort()).toEqual(
      ["ageDays", "folder", "id", "label", "r", "side", "title", "x", "y"],
    );
  });

  test("handles no notes", () => {
    const chart = layoutStarChart([], [], NOW);
    expect(chart.stars).toEqual([]);
    expect(chart.lines).toEqual([]);
    expect(chart.rings).toEqual([]);
  });

  test("shortens long labels and keeps the background field stable", () => {
    expect(shortLabel("Short")).toBe("Short");
    expect(shortLabel("2026-09-05 - could you review the whole thing")).toHaveLength(22);
    expect(starField(1, 5)).toEqual(starField(1, 5));
  });
});
