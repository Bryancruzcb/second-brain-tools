import type { HealthIssue, Note } from "@/types";
import { layoutGraph as layoutVaultGraph } from "./graphLayout";

export type { GraphCluster, GraphLayout } from "./graphLayout";
export { folderCluster, isChatNote } from "./graphLayout";

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

async function apiResponse(path: string, init?: RequestInit): Promise<Response> {
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
  return res;
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiResponse(path, init);
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

/** Client-side layout for graph nodes (API has no x/y). Caps for readability. */
export function layoutGraph(
  nodes: BackendGraphNode[],
  edges: BackendGraphEdge[],
  opts: {
    width?: number;
    height?: number;
    maxNodes?: number;
    includeChats?: boolean;
  } = {},
) {
  return layoutVaultGraph(nodes, edges, opts);
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

export type SearchHit = {
  title: string;
  id: string;
  snippet: string;
};

export async function searchNotes(q: string, scope: AskScope = "notes") {
  const params = new URLSearchParams({ q, scope });
  return apiFetch<{ results: SearchHit[] }>(`/api/search?${params.toString()}`);
}

export async function saveNote(noteRef: string, content: string) {
  const enc = encodeURIComponent(noteRef).replace(/%2F/gi, "/");
  return apiFetch<{ status: string; message?: string }>(`/api/note/${enc}`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export async function scanHealth() {
  return apiFetch<{ status: string; message: string }>("/api/health/scan", {
    method: "POST",
  });
}

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

type AskStreamEvent =
  | { type: "sources"; sources: BackendQuerySource[]; api_configured: boolean }
  | { type: "token"; text: string }
  | { type: "done" }
  | { type: "error"; detail: string };

/**
 * askQuery over POST /api/query/stream: onSources fires as soon as retrieval
 * is done, onToken for each piece of the answer as the model writes it.
 * Resolves with the full answer.
 */
export async function askQueryStream(
  opts: Parameters<typeof askQuery>[0],
  handlers: {
    onSources: (sources: BackendQuerySource[]) => void;
    onToken: (text: string) => void;
  },
): Promise<string> {
  const res = await apiResponse("/api/query/stream", {
    method: "POST",
    headers: { Accept: "application/x-ndjson" },
    body: JSON.stringify({
      query: opts.query,
      context_nodes: opts.contextNodes?.length ? opts.contextNodes : undefined,
      history: opts.history,
      scope: opts.scope ?? "notes",
    }),
  });
  if (!res.body) throw new ApiError("Streaming is not supported here.", 0);
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffered = "";
  let answer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffered += value;
    const lines = buffered.split("\n");
    buffered = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line) as AskStreamEvent;
      if (event.type === "sources") handlers.onSources(event.sources);
      else if (event.type === "token") {
        answer += event.text;
        handlers.onToken(event.text);
      } else if (event.type === "error") throw new ApiError(event.detail, 0);
      else if (event.type === "done") return answer;
    }
  }
  throw new ApiError("The answer stream ended early.", 0);
}

export const composePrompts = [
  "What themes show up across my recent notes?",
  "Summarize vault health issues to fix",
  "Which notes are most connected?",
];
