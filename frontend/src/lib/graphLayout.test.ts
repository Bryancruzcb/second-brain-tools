import { describe, expect, test } from "bun:test";
import { layoutGraph, type LayoutEdge, type LayoutNode } from "./graphLayout";

function node(id: string, label: string, cluster_id = 0): LayoutNode {
  return { id, label, cluster_id };
}

function dist(
  a: { x: number; y: number },
  b: { x: number; y: number },
): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

describe("layoutGraph", () => {
  test("drops chat archives unless includeChats is set", () => {
    const nodes = [
      node("00 Home/Home.md", "Home"),
      node("05 AI Chats/2026-07-19 - eval harness.md", "2026-07-19 - eval harness"),
      node("03 School/Graphs.md", "Graphs"),
    ];
    const edges: LayoutEdge[] = [
      { source: "05 AI Chats/2026-07-19 - eval harness.md", target: "03 School/Graphs.md" },
      { source: "05 AI Chats/2026-07-19 - eval harness.md", target: "00 Home/Home.md" },
    ];

    const hidden = layoutGraph(nodes, edges, { maxNodes: 12 });
    expect(hidden.nodes.map((n) => n.id).sort()).toEqual([
      "00 Home/Home.md",
      "03 School/Graphs.md",
    ]);
    expect(hidden.hiddenChats).toBe(1);

    const shown = layoutGraph(nodes, edges, { maxNodes: 12, includeChats: true });
    expect(shown.nodes.some((n) => n.id.includes("05 AI Chats"))).toBe(true);
  });

  test("clusters by folder, not KMeans cluster_id", () => {
    const nodes = [
      node("00 Home/Home.md", "Home", 7),
      node("02 Projects/CreatorFlow.md", "CreatorFlow", 7),
      node("03 School/Graphs.md", "Graphs", 7),
      node("01 Memory/Master Context.md", "Master Context", 7),
    ];
    const laid = layoutGraph(nodes, [], { width: 640, height: 400, maxNodes: 12 });
    const clusters = new Set(laid.nodes.map((n) => n.cluster));
    expect(clusters).toEqual(new Set(["Home", "Projects", "School", "Memory"]));
    expect(laid.clusters.map((c) => c.label).sort()).toEqual([
      "Home",
      "Memory",
      "Projects",
      "School",
    ]);
  });

  test("round-robins folders so one topic cannot fill the map", () => {
    const nodes: LayoutNode[] = [node("00 Home/Home.md", "Home")];
    const edges: LayoutEdge[] = [];
    for (let i = 0; i < 30; i++) {
      const id = `03 School/Note ${i}.md`;
      nodes.push(node(id, `Note ${i}`));
      edges.push({ source: "00 Home/Home.md", target: id });
    }
    nodes.push(node("02 Projects/CreatorFlow.md", "CreatorFlow"));
    edges.push({ source: "00 Home/Home.md", target: "02 Projects/CreatorFlow.md" });

    const laid = layoutGraph(nodes, edges, { maxNodes: 12 });
    const folders = laid.nodes.map((n) => n.cluster);
    expect(folders).toContain("Home");
    expect(folders).toContain("Projects");
    expect(folders.filter((f) => f === "School").length).toBeLessThan(12);
    expect(new Set(folders).size).toBe(3);
  });

  test("keeps hubs even when they have fewer links than siblings", () => {
    const nodes = [
      node("00 Home/Home.md", "Home"),
      node("03 School/Course Home.md", "Course Home"),
    ];
    const edges: LayoutEdge[] = [];
    for (let i = 0; i < 8; i++) {
      const id = `03 School/Algo ${i}.md`;
      nodes.push(node(id, `Algo ${i}`));
      edges.push({ source: id, target: "03 School/Course Home.md" });
    }
    const laid = layoutGraph(nodes, edges, { maxNodes: 6 });
    expect(laid.nodes.some((n) => n.id === "00 Home/Home.md")).toBe(true);
    expect(laid.nodes.some((n) => n.id === "03 School/Course Home.md")).toBe(true);
  });

  test("spaces nodes far enough that labels can sit beside them", () => {
    const nodes: LayoutNode[] = [
      node("00 Home/Home.md", "Home"),
      node("02 Projects/CreatorFlow.md", "CreatorFlow"),
      node("03 School/Graphs.md", "Graphs"),
      node("03 School/Hash Tables.md", "Hash Tables"),
      node("01 Memory/Master Context.md", "Master Context"),
      node("04 Career/Resume.md", "Resume"),
    ];
    const laid = layoutGraph(nodes, [], { width: 640, height: 400, maxNodes: 12 });
    expect(laid.nodes.length).toBe(6);
    for (let i = 0; i < laid.nodes.length; i++) {
      for (let j = i + 1; j < laid.nodes.length; j++) {
        expect(dist(laid.nodes[i], laid.nodes[j])).toBeGreaterThanOrEqual(48);
      }
      expect(laid.nodes[i].x).toBeGreaterThan(20);
      expect(laid.nodes[i].x).toBeLessThan(620);
      expect(laid.nodes[i].y).toBeGreaterThan(20);
      expect(laid.nodes[i].y).toBeLessThan(380);
    }
  });

  test("skips ghost edges and reports vault size", () => {
    const nodes = [
      node("00 Home/Home.md", "Home"),
      node("03 School/Graphs.md", "Graphs"),
    ];
    const edges: LayoutEdge[] = [
      { source: "00 Home/Home.md", target: "03 School/Graphs.md" },
      { source: "00 Home/Home.md", target: "03 School/Graphs.md", is_ghost: true },
    ];
    const laid = layoutGraph(nodes, edges);
    expect(laid.edges).toEqual([["00 Home/Home.md", "03 School/Graphs.md"]]);
    expect(laid.totalNodes).toBe(2);
    expect(laid.shownNodes).toBe(2);
    expect(laid.labels["00 Home/Home.md"]).toBe("Home");
    expect(laid.degrees["00 Home/Home.md"]).toBe(1);
    expect(laid.degrees["03 School/Graphs.md"]).toBe(1);
  });
});
