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
  /** dot radius in world units (4–9 for notes, 3.5 for chats) */
  r: number;
  cluster: string;
  /** links to other shown nodes (ghost edges excluded) */
  degree: number;
  chat: boolean;
};

export type GraphCluster = {
  key: string;
  label: string;
  cx: number;
  cy: number;
  /** halo radius; rx/ry kept equal for older callers */
  r: number;
  rx: number;
  ry: number;
  size: number;
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
  /** world-space extent of everything laid out (nodes + halos) */
  width: number;
  height: number;
};

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));

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

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

/** Node spacing shrinks as the vault grows so a whole vault stays compact. */
function spacingFor(count: number): number {
  if (count <= 40) return 56;
  if (count <= 150) return 42;
  if (count <= 500) return 34;
  return 28;
}

/** Push points apart until they are minSep apart (O(n²) per round). */
function separate(pts: { x: number; y: number }[], minSep: number, rounds = 12): void {
  for (let round = 0; round < rounds; round++) {
    let moved = false;
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        let dx = pts[j].x - pts[i].x;
        let dy = pts[j].y - pts[i].y;
        let d = Math.hypot(dx, dy);
        if (d >= minSep) continue;
        if (d < 0.01) {
          dx = 0.01;
          dy = 0;
          d = 0.01;
        }
        const push = (minSep - d) / 2;
        const ux = dx / d;
        const uy = dy / d;
        pts[i].x -= ux * push;
        pts[i].y -= uy * push;
        pts[j].x += ux * push;
        pts[j].y += uy * push;
        moved = true;
      }
    }
    if (!moved) break;
  }
}

/**
 * Sunflower (Vogel) disc: best-ranked node in the middle, the rest spiralling
 * out. Even spacing without an O(n²) simulation, so whole vaults lay out fast.
 */
function sunflower(count: number, c: number): { x: number; y: number }[] {
  const pts: { x: number; y: number }[] = [];
  if (count === 1) return [{ x: 0, y: 0 }];
  for (let i = 0; i < count; i++) {
    const r = c * Math.sqrt(i + 0.5);
    const a = i * GOLDEN_ANGLE;
    pts.push({ x: r * Math.cos(a), y: r * Math.sin(a) });
  }
  return pts;
}

/**
 * Greedy circle packing of folder discs around the largest one. Distance is
 * measured with a horizontal stretch so the result suits a landscape panel.
 */
function packClusters(
  discs: { key: string; r: number }[],
  gap: number,
): Map<string, { x: number; y: number }> {
  const placed: { key: string; x: number; y: number; r: number }[] = [];
  const out = new Map<string, { x: number; y: number }>();
  for (const d of discs) {
    if (placed.length === 0) {
      placed.push({ ...d, x: 0, y: 0 });
      out.set(d.key, { x: 0, y: 0 });
      continue;
    }
    let best: { x: number; y: number; score: number } | null = null;
    const anchors = placed;
    for (const a of anchors) {
      const dist = a.r + d.r + gap;
      for (let k = 0; k < 48; k++) {
        const ang = (2 * Math.PI * k) / 48;
        const x = a.x + dist * Math.cos(ang);
        const y = a.y + dist * Math.sin(ang);
        let ok = true;
        for (const p of placed) {
          if (Math.hypot(p.x - x, p.y - y) < p.r + d.r + gap - 0.5) {
            ok = false;
            break;
          }
        }
        if (!ok) continue;
        const score = Math.hypot(x / 1.25, y);
        if (!best || score < best.score) best = { x, y, score };
      }
    }
    const pos = best ?? { x: 0, y: 0 };
    placed.push({ ...d, x: pos.x, y: pos.y });
    out.set(d.key, { x: pos.x, y: pos.y });
  }
  return out;
}

export function nodeRadius(degree: number, chat = false): number {
  if (chat) return 3.5;
  return clamp(4 + Math.sqrt(degree) * 1.25, 4, 9);
}

export function layoutGraph(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  opts: {
    width?: number;
    height?: number;
    /** cap on shown nodes; omit to lay out the whole vault */
    maxNodes?: number;
    includeChats?: boolean;
  } = {},
): GraphLayout {
  const width = opts.width ?? 640;
  const height = opts.height ?? 400;
  const maxNodes = opts.maxNodes ?? Number.POSITIVE_INFINITY;
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
    width,
    height,
  };
  if (pool.length === 0) return empty;

  const degree = degreeMap(pool, edges);
  const selected = selectNodes(pool, degree, maxNodes);
  const selectedIds = new Set(selected.map((n) => n.id));

  // Real (non-ghost) edges between shown nodes, deduplicated.
  const edgePairs: [string, string][] = [];
  const seen = new Set<string>();
  const neighbors = new Map<string, string[]>();
  for (const e of edges) {
    if (e.is_ghost || e.source === e.target) continue;
    if (!selectedIds.has(e.source) || !selectedIds.has(e.target)) continue;
    const key = [e.source, e.target].sort().join("\0");
    if (seen.has(key)) continue;
    seen.add(key);
    edgePairs.push([e.source, e.target]);
    for (const [a, b] of [
      [e.source, e.target],
      [e.target, e.source],
    ]) {
      const list = neighbors.get(a) || [];
      list.push(b);
      neighbors.set(a, list);
    }
  }

  // Chats that link to notes sit next to those notes; the rest get a disc.
  const floatingChats: LayoutNode[] = [];
  const discMembers = new Map<string, LayoutNode[]>();
  for (const n of selected) {
    const chat = isChatNote(n.id);
    if (chat && (neighbors.get(n.id) || []).some((m) => !isChatNote(m))) {
      floatingChats.push(n);
      continue;
    }
    const key = folderCluster(n.id);
    const list = discMembers.get(key) || [];
    list.push(n);
    discMembers.set(key, list);
  }

  const noteCount = selected.length - floatingChats.length;
  const spacing = spacingFor(noteCount);
  const c = spacing * 0.6;
  const haloPad = spacing * 0.9;
  const rank = rankFn(degree);

  const local = new Map<string, { x: number; y: number }>();
  const discs: { key: string; r: number }[] = [];
  for (const [key, members] of discMembers) {
    members.sort(rank);
    const pts = sunflower(members.length, c);
    if (members.length <= 400) separate(pts, spacing * 0.95);
    let maxR = 0;
    members.forEach((n, i) => {
      local.set(n.id, pts[i]);
      maxR = Math.max(maxR, Math.hypot(pts[i].x, pts[i].y));
    });
    discs.push({ key, r: maxR + haloPad });
  }
  discs.sort((a, b) => b.r - a.r || a.key.localeCompare(b.key));
  const centers = packClusters(discs, spacing * 0.35);

  const pos = new Map<string, { x: number; y: number }>();
  for (const [key, members] of discMembers) {
    const center = centers.get(key) || { x: 0, y: 0 };
    for (const n of members) {
      const p = local.get(n.id) || { x: 0, y: 0 };
      pos.set(n.id, { x: center.x + p.x, y: center.y + p.y });
    }
  }

  // Linked chats: spiral around the centroid of the notes they link to.
  const crowd = new Map<string, number>();
  for (const n of floatingChats) {
    const linked = (neighbors.get(n.id) || [])
      .map((m) => pos.get(m))
      .filter((p): p is { x: number; y: number } => Boolean(p));
    const cx = linked.reduce((s, p) => s + p.x, 0) / linked.length;
    const cy = linked.reduce((s, p) => s + p.y, 0) / linked.length;
    const slot = `${Math.round(cx / 8)}:${Math.round(cy / 8)}`;
    const k = crowd.get(slot) || 0;
    crowd.set(slot, k + 1);
    const r = spacing * 0.45 * Math.sqrt(k + 1);
    const a = (k + 1) * GOLDEN_ANGLE;
    pos.set(n.id, { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) });
  }

  const clusters: GraphCluster[] = discs.map((d) => {
    const center = centers.get(d.key) || { x: 0, y: 0 };
    return {
      key: d.key,
      label: d.key,
      cx: center.x,
      cy: center.y,
      r: d.r,
      rx: d.r,
      ry: d.r,
      size: (discMembers.get(d.key) || []).length,
    };
  });

  // Normalise into positive world space; small graphs are centred in the box.
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const cl of clusters) {
    minX = Math.min(minX, cl.cx - cl.r);
    maxX = Math.max(maxX, cl.cx + cl.r);
    minY = Math.min(minY, cl.cy - cl.r);
    maxY = Math.max(maxY, cl.cy + cl.r);
  }
  for (const p of pos.values()) {
    minX = Math.min(minX, p.x - spacing);
    maxX = Math.max(maxX, p.x + spacing);
    minY = Math.min(minY, p.y - spacing);
    maxY = Math.max(maxY, p.y + spacing);
  }
  const bw = maxX - minX;
  const bh = maxY - minY;
  const worldW = Math.max(width, bw);
  const worldH = Math.max(height, bh);
  const dx = (worldW - bw) / 2 - minX;
  const dy = (worldH - bh) / 2 - minY;
  for (const p of pos.values()) {
    p.x += dx;
    p.y += dy;
  }
  for (const cl of clusters) {
    cl.cx += dx;
    cl.cy += dy;
  }

  const shownDegree = new Map<string, number>();
  for (const [a, b] of edgePairs) {
    shownDegree.set(a, (shownDegree.get(a) || 0) + 1);
    shownDegree.set(b, (shownDegree.get(b) || 0) + 1);
  }

  const laid: LaidNode[] = selected.map((n) => {
    const p = pos.get(n.id) || { x: worldW / 2, y: worldH / 2 };
    const chat = isChatNote(n.id);
    const deg = shownDegree.get(n.id) || 0;
    return {
      id: n.id,
      x: p.x,
      y: p.y,
      r: nodeRadius(deg, chat),
      cluster: folderCluster(n.id),
      degree: deg,
      chat,
    };
  });

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
    width: worldW,
    height: worldH,
  };
}
