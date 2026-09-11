import type { GraphNode, HealthIssue, Note } from "@/types";

export const API_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL) ||
  "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError("Backend unreachable. Is FastAPI running on :8000?", 0);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (body?.detail)
        detail =
          typeof body.detail === "string"
            ? body.detail
            : JSON.stringify(body.detail);
    } catch {
      /* ignore */
    }
    throw new ApiError(detail || `Request failed (${res.status})`, res.status);
  }
  return res.json() as Promise<T>;
}

/* ---------- backend shapes ---------- */

export type BackendGraphNode = {
  id: string;
  label: string;
  tags?: string[];
  cluster_id?: number;
};

export type BackendGraphEdge = {
  source: string;
  target: string;
  is_ghost?: boolean;
};

export type BackendRecentNote = {
  title: string;
  id: string;
  mtime: number;
  preview?: string;
};

export type BackendBrokenLink = {
  source: string;
  source_title: string;
  target: string;
};

export type BackendOrphanedNote = {
  path: string;
  title: string;
};

export type BackendTaglessNote = {
  path: string;
  title: string;
  suggestions?: string[];
};

export type BackendHealthData = {
  total_notes?: number;
  total_links?: number;
  avg_links_per_note?: number;
  broken_links?: BackendBrokenLink[];
  orphaned_notes?: BackendOrphanedNote[];
  tagless_notes?: BackendTaglessNote[];
  nodes?: BackendGraphNode[];
  edges?: BackendGraphEdge[];
};

export type BackendQuerySource = {
  title: string;
  source: string;
  snippet?: string;
  distance?: number;
};

export type BackendQueryResponse = {
  answer: string;
  sources: BackendQuerySource[];
  api_configured: boolean;
};

/* ---------- adapters ---------- */

function mtimeToIso(mtime: number): string {
  const ms = mtime > 1e12 ? mtime : mtime * 1000;
  return new Date(ms).toISOString();
}

export function recentToNote(r: BackendRecentNote): Note {
  const path = r.id;
  return {
    id: r.id,
    title: r.title,
    path,
    tags: [],
    excerpt: (r.preview || "").replace(/\s+/g, " ").trim().slice(0, 160),
    body: r.preview || "",
    updatedAt: mtimeToIso(r.mtime),
    links: [],
    backlinks: [],
  };
}

export function graphNodeToNoteStub(n: BackendGraphNode): Note {
  return {
    id: n.id,
    title: n.label || n.id,
    path: n.id,
    tags: n.tags || [],
    excerpt: "",
    body: "",
    updatedAt: new Date().toISOString(),
    links: [],
    backlinks: [],
  };
}

export function mapHealthIssues(data: BackendHealthData): HealthIssue[] {
  const issues: HealthIssue[] = [];
  let i = 0;

  for (const bl of data.broken_links || []) {
    i += 1;
    issues.push({
      id: `broken-${i}`,
      kind: "broken-link",
      noteId: bl.source,
      title: bl.source_title || bl.source,
      detail: `Points at missing \u201c${bl.target}\u201d.`,
      action: "Retarget or create the target note",
    });
  }

  for (const o of data.orphaned_notes || []) {
    i += 1;
    issues.push({
      id: `orphan-${i}`,
      kind: "orphan",
      noteId: o.path,
      title: o.title || o.path,
      detail: "Zero backlinks \u00b7 not cited by any hub.",
      action: "Link from a hub or MOC",
    });
  }

  for (const t of data.tagless_notes || []) {
    i += 1;
    const suggestions = (t.suggestions || []).slice(0, 3).join(" \u00b7 ");
    issues.push({
      id: `tagless-${i}`,
      kind: "tagless",
      noteId: t.path,
      title: t.title || t.path,
      detail: suggestions ? `No tags. Suggested: ${suggestions}.` : "No tags.",
      action: suggestions ? "Apply suggested tags" : "Add tags",
    });
  }

  return issues;
}

/** Ring spacing inside a cluster, in layout units; wide enough for a label between rings. */
const RING_STEP = 38;
const RING_ARC = 52;

/**
 * Offsets for `count` cluster members: the first (highest-degree) member sits
 * at the centre, the rest fill concentric rings whose capacity grows with the
 * radius, so labels have room instead of piling onto one small circle.
 */
function ringOffsets(count: number): { dx: number; dy: number }[] {
  const out: { dx: number; dy: number }[] = [];
  if (count <= 0) return out;
  out.push({ dx: 0, dy: 0 });
  for (let k = 1; out.length < count; k++) {
    const r = RING_STEP * k + 8;
    const capacity = Math.max(6, Math.floor((2 * Math.PI * r) / RING_ARC));
    const n = Math.min(capacity, count - out.length);
    const phase = k % 2 === 0 ? Math.PI / n : 0;
    for (let i = 0; i < n; i++) {
      const a = (2 * Math.PI * i) / n + phase - Math.PI / 2;
      out.push({ dx: r * Math.cos(a), dy: r * Math.sin(a) });
    }
  }
  return out;
}

/** Client-side layout for graph nodes (API has no x/y). Caps for readability. */
export function layoutGraph(
  nodes: BackendGraphNode[],
  edges: BackendGraphEdge[],
  opts: { width?: number; height?: number; maxNodes?: number } = {},
): {
  nodes: GraphNode[];
  edges: [string, string][];
  labels: Record<string, string>;
  /** Link count per node over the whole vault graph, not just the shown subset. */
  degrees: Record<string, number>;
  totalNodes: number;
  shownNodes: number;
} {
  const width = opts.width ?? 960;
  const height = opts.height ?? 560;
  const maxNodes = opts.maxNodes ?? 42;
  const totalNodes = nodes.length;

  // Rank by real wikilinks. Ghost edges are suggested links; they outnumber
  // real ones ~9:1 in a chat-heavy vault and are never drawn, so counting them
  // would pick nodes that share no visible edge.
  const realEdges = edges.filter((e) => !e.is_ghost);
  const rankEdges = realEdges.length > 0 ? realEdges : edges;
  const degree = new Map<string, number>();
  for (const n of nodes) degree.set(n.id, 0);
  for (const e of rankEdges) {
    if (degree.has(e.source))
      degree.set(e.source, (degree.get(e.source) || 0) + 1);
    if (degree.has(e.target))
      degree.set(e.target, (degree.get(e.target) || 0) + 1);
  }

  const ranked = [...nodes].sort(
    (a, b) => (degree.get(b.id) || 0) - (degree.get(a.id) || 0),
  );
  const linked = ranked.filter((n) => (degree.get(n.id) || 0) > 0);
  // Prefer notes that actually connect; a tiny vault falls back to any notes.
  const selected = (linked.length >= 8 ? linked : ranked).slice(0, maxNodes);
  const selectedIds = new Set(selected.map((n) => n.id));

  const byCluster = new Map<string, BackendGraphNode[]>();
  for (const n of selected) {
    const key = String(n.cluster_id ?? (n.tags?.[0] ?? "vault"));
    const list = byCluster.get(key) || [];
    list.push(n);
    byCluster.set(key, list);
  }

  const clusters = [...byCluster.keys()];
  const clusterCount = Math.max(1, clusters.length);
  const cx = width / 2;
  const cy = height / 2;
  // Clusters sit on an ellipse that follows the canvas shape; one cluster sits centred.
  const ringRx = clusterCount === 1 ? 0 : width * 0.34;
  const ringRy = clusterCount === 1 ? 0 : height * 0.3;

  const positions = new Map<string, { x: number; y: number; cluster: string }>();
  clusters.forEach((key, ci) => {
    const angle = (2 * Math.PI * ci) / clusterCount - Math.PI / 2;
    const clusterCx = cx + ringRx * Math.cos(angle);
    const clusterCy = cy + ringRy * Math.sin(angle);
    const members = byCluster.get(key)!;
    const offsets = ringOffsets(members.length);
    members.forEach((n, mi) => {
      const { dx, dy } = offsets[mi];
      positions.set(n.id, {
        x: Math.max(24, Math.min(width - 24, clusterCx + dx)),
        y: Math.max(28, Math.min(height - 36, clusterCy + dy)),
        cluster: key,
      });
    });
  });

  const laid: GraphNode[] = selected.map((n) => {
    const p = positions.get(n.id)!;
    const deg = degree.get(n.id) || 0;
    const r = Math.max(5, Math.min(11, 5 + Math.sqrt(deg)));
    return { id: n.id, x: p.x, y: p.y, r, cluster: p.cluster };
  });

  const edgePairs: [string, string][] = [];
  const seen = new Set<string>();
  for (const e of edges) {
    if (!selectedIds.has(e.source) || !selectedIds.has(e.target)) continue;
    if (e.is_ghost) continue;
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
    totalNodes,
    shownNodes: laid.length,
  };
}

/* ---------- endpoints ---------- */

export async function fetchReady() {
  return apiFetch<{ ready: boolean; components: Record<string, boolean> }>(
    "/api/ready",
  );
}

export async function fetchHealth() {
  return apiFetch<{
    data: BackendHealthData;
    is_scanning: boolean;
    last_scan_time: number;
  }>("/api/health");
}

let healthPromise: ReturnType<typeof fetchHealth> | null = null;

/**
 * One /api/health request shared by every panel on the page. A failure clears
 * the cache so the next caller retries instead of replaying the error.
 */
export function fetchHealthCached() {
  if (!healthPromise) {
    healthPromise = fetchHealth().catch((e) => {
      healthPromise = null;
      throw e;
    });
  }
  return healthPromise;
}

export async function fetchGraph() {
  return apiFetch<{ nodes: BackendGraphNode[]; edges: BackendGraphEdge[] }>(
    "/api/graph",
  );
}

export async function fetchRecent() {
  return apiFetch<{ notes: BackendRecentNote[] }>("/api/recent");
}

export async function fetchNote(noteRef: string) {
  const enc = encodeURIComponent(noteRef).replace(/%2F/gi, "/");
  return apiFetch<{
    title: string;
    content: string;
    read_only_fallback?: boolean;
  }>(`/api/note/${enc}`);
}

export type AskScope = "notes" | "chats" | "all";

export async function askQuery(opts: {
  query: string;
  contextNodes?: string[];
  history?: { role: string; content: string }[];
  /** notes = written notes only (default); chats = AI transcripts; all = both */
  scope?: AskScope;
}) {
  return apiFetch<BackendQueryResponse>("/api/query", {
    method: "POST",
    body: JSON.stringify({
      query: opts.query,
      context_nodes: opts.contextNodes?.length ? opts.contextNodes : undefined,
      history: opts.history,
      scope: opts.scope ?? "notes",
    }),
  });
}

export const composePrompts = [
  "What themes show up across my recent notes?",
  "Summarize vault health issues to fix",
  "Which notes are most connected?",
];
