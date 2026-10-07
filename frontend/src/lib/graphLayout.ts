export type LayoutNode = {
  id: string;
  label: string;
  tags?: string[];
  cluster_id?: number;
};

export type LayoutEdge = {
  source: string;
  target: string;
  is_ghost?: boolean;
};

export type LaidNode = {
  id: string;
  x: number;
  y: number;
  r: number;
  cluster: string;
};

export type GraphCluster = {
  key: string;
  label: string;
  cx: number;
  cy: number;
  rx: number;
  ry: number;
};

export type GraphLayout = {
  nodes: LaidNode[];
  edges: [string, string][];
  labels: Record<string, string>;
  degrees: Record<string, number>;
  clusters: GraphCluster[];
  totalNodes: number;
  shownNodes: number;
  hiddenChats: number;
};

const MIN_SEP = 56;

function normalizePath(id: string): string {
  return id.replace(/\\/g, "/");
}

export function isChatNote(id: string): boolean {
  const path = normalizePath(id);
  return path.startsWith("05 AI Chats/") || path.includes("/05 AI Chats/");
}

export function folderCluster(id: string): string {
  const path = normalizePath(id);
  if (isChatNote(path)) return "Chats";
  const slash = path.indexOf("/");
  if (slash < 0) return "Vault";
  const first = path.slice(0, slash);
  const stripped = first.replace(/^\d+\s+/, "").trim();
  return stripped || "Vault";
}

function hubScore(id: string, label: string): number {
  const path = normalizePath(id).toLowerCase();
  const title = label.toLowerCase();
  if (path.includes("00 home/") || title === "home") return 4;
  if (title === "course home" || title === "master context") return 3;
  if (title === "index" || /\/index\.md$/.test(path) || /\bmoc\b/.test(title))
    return 3;
  if (/\bhub\b/.test(title)) return 2;
  return 0;
}

function degreeMap(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
): Map<string, number> {
  const degree = new Map<string, number>();
  for (const n of nodes) degree.set(n.id, 0);
  for (const e of edges) {
    if (e.is_ghost) continue;
    if (degree.has(e.source)) degree.set(e.source, (degree.get(e.source) || 0) + 1);
    if (degree.has(e.target)) degree.set(e.target, (degree.get(e.target) || 0) + 1);
  }
  return degree;
}

function rankFn(degree: Map<string, number>) {
  return (a: LayoutNode, b: LayoutNode) => {
    const hubs = hubScore(b.id, b.label) - hubScore(a.id, a.label);
    if (hubs) return hubs;
    return (degree.get(b.id) || 0) - (degree.get(a.id) || 0);
  };
}

function selectNodes(
  pool: LayoutNode[],
  degree: Map<string, number>,
  maxNodes: number,
): LayoutNode[] {
  if (pool.length <= maxNodes) return [...pool];
  const groups = new Map<string, LayoutNode[]>();
  for (const n of pool) {
    const key = folderCluster(n.id);
    const list = groups.get(key) || [];
    list.push(n);
    groups.set(key, list);
  }
  const rank = rankFn(degree);
  const folders = [...groups.keys()].sort();
  const queues = folders.map((f) => [...(groups.get(f) || [])].sort(rank));
  const selected: LayoutNode[] = [];
  const cap = Math.max(3, Math.ceil(maxNodes / 2));
  const taken = new Map<string, number>();
  let progressed = true;
  while (selected.length < maxNodes && progressed) {
    progressed = false;
    for (let i = 0; i < queues.length; i++) {
      if (selected.length >= maxNodes) break;
      const folder = folders[i];
      if ((taken.get(folder) || 0) >= cap) continue;
      const n = queues[i].shift();
      if (!n) continue;
      selected.push(n);
      taken.set(folder, (taken.get(folder) || 0) + 1);
      progressed = true;
    }
  }
  if (selected.length < maxNodes) {
    const leftover = queues.flat().sort(rank);
    for (const n of leftover) {
      if (selected.length >= maxNodes) break;
      selected.push(n);
    }
  }
  return selected;
}

function neededRadius(count: number): number {
  if (count <= 1) return 22;
  return Math.max(36, (MIN_SEP * count) / (2 * Math.PI));
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function separate(
  pts: { x: number; y: number }[],
  minSep: number,
  bounds: { minX: number; maxX: number; minY: number; maxY: number },
): void {
  for (let round = 0; round < 18; round++) {
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        let dx = pts[j].x - pts[i].x;
        let dy = pts[j].y - pts[i].y;
        let d = Math.hypot(dx, dy);
        if (d < 0.01) {
          dx = 0.01;
          dy = 0;
          d = 0.01;
        }
        if (d >= minSep) continue;
        const push = (minSep - d) / 2;
        const ux = dx / d;
        const uy = dy / d;
        pts[i].x -= ux * push;
        pts[i].y -= uy * push;
        pts[j].x += ux * push;
        pts[j].y += uy * push;
      }
      pts[i].x = clamp(pts[i].x, bounds.minX, bounds.maxX);
      pts[i].y = clamp(pts[i].y, bounds.minY, bounds.maxY);
    }
  }
}

export function layoutGraph(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  opts: {
    width?: number;
    height?: number;
    maxNodes?: number;
    includeChats?: boolean;
  } = {},
): GraphLayout {
  const width = opts.width ?? 640;
  const height = opts.height ?? 400;
  const maxNodes = opts.maxNodes ?? 24;
  const includeChats = opts.includeChats ?? false;
  const totalNodes = nodes.length;
  const chatCount = nodes.filter((n) => isChatNote(n.id)).length;
  const pool = includeChats ? nodes : nodes.filter((n) => !isChatNote(n.id));
  const hiddenChats = includeChats ? 0 : chatCount;

  const empty: GraphLayout = {
    nodes: [],
    edges: [],
    labels: {},
    degrees: {},
    clusters: [],
    totalNodes,
    shownNodes: 0,
    hiddenChats,
  };
  if (pool.length === 0) return empty;

  const degree = degreeMap(pool, edges);
  const selected = selectNodes(pool, degree, maxNodes);
  const selectedIds = new Set(selected.map((n) => n.id));

  const byCluster = new Map<string, LayoutNode[]>();
  for (const n of selected) {
    const key = folderCluster(n.id);
    const list = byCluster.get(key) || [];
    list.push(n);
    byCluster.set(key, list);
  }
  const clusterKeys = [...byCluster.keys()].sort();
  const cx = width / 2;
  const cy = height / 2;
  const padX = 56;
  const padY = 48;
  const bounds = {
    minX: padX,
    maxX: width - padX,
    minY: padY,
    maxY: height - padY,
  };

  const radii = clusterKeys.map((k) => neededRadius((byCluster.get(k) || []).length));
  const clusterCenters = new Map<string, { x: number; y: number; r: number }>();
  if (clusterKeys.length === 1) {
    clusterCenters.set(clusterKeys[0], { x: cx, y: cy, r: radii[0] });
  } else {
    const nC = clusterKeys.length;
    let maxPair = 0;
    for (let i = 0; i < nC; i++) {
      const j = (i + 1) % nC;
      maxPair = Math.max(maxPair, radii[i] + radii[j] + 28);
    }
    const ring = maxPair / (2 * Math.sin(Math.PI / nC));
    const rx = Math.min((width - 2 * padX) / 2 - 8, Math.max(110, ring));
    const ry = Math.min((height - 2 * padY) / 2 - 8, Math.max(78, ring * 0.7));
    clusterKeys.forEach((key, i) => {
      const angle = (2 * Math.PI * i) / nC - Math.PI / 2;
      clusterCenters.set(key, {
        x: cx + rx * Math.cos(angle),
        y: cy + ry * Math.sin(angle),
        r: radii[i],
      });
    });
  }

  const pos = new Map<string, { x: number; y: number }>();
  for (const key of clusterKeys) {
    const members = byCluster.get(key) || [];
    const center = clusterCenters.get(key);
    if (!center) continue;
    if (members.length === 1) {
      pos.set(members[0].id, { x: center.x, y: center.y });
      continue;
    }
    members.forEach((n, i) => {
      const angle = (2 * Math.PI * i) / members.length - Math.PI / 2;
      pos.set(n.id, {
        x: center.x + center.r * Math.cos(angle),
        y: center.y + center.r * Math.sin(angle),
      });
    });
  }

  const pts = selected.map((n) => pos.get(n.id) || { x: cx, y: cy });
  separate(pts, MIN_SEP, bounds);
  selected.forEach((n, i) => pos.set(n.id, pts[i]));

  const laid: LaidNode[] = selected.map((n) => {
    const p = pos.get(n.id) || { x: cx, y: cy };
    const deg = degree.get(n.id) || 0;
    return {
      id: n.id,
      x: p.x,
      y: p.y,
      r: Math.max(5, Math.min(11, 5 + Math.sqrt(deg))),
      cluster: folderCluster(n.id),
    };
  });

  const clusters: GraphCluster[] = clusterKeys.map((key) => {
    const members = laid.filter((n) => n.cluster === key);
    const mx = members.reduce((s, n) => s + n.x, 0) / members.length;
    const my = members.reduce((s, n) => s + n.y, 0) / members.length;
    const rx = Math.max(32, ...members.map((n) => Math.abs(n.x - mx) + 28));
    const ry = Math.max(26, ...members.map((n) => Math.abs(n.y - my) + 24));
    return { key, label: key, cx: mx, cy: my, rx, ry };
  });

  const edgePairs: [string, string][] = [];
  const seen = new Set<string>();
  for (const e of edges) {
    if (e.is_ghost) continue;
    if (!selectedIds.has(e.source) || !selectedIds.has(e.target)) continue;
    const key = [e.source, e.target].sort().join("\0");
    if (seen.has(key)) continue;
    seen.add(key);
    edgePairs.push([e.source, e.target]);
  }

  const labels: Record<string, string> = {};
  const degrees: Record<string, number> = {};
  for (const n of selected) {
    labels[n.id] = n.label || n.id;
    degrees[n.id] = degree.get(n.id) || 0;
  }

  return {
    nodes: laid,
    edges: edgePairs,
    labels,
    degrees,
    clusters,
    totalNodes,
    shownNodes: laid.length,
    hiddenChats,
  };
}
