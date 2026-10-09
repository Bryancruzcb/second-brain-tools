// Request logic for POST /api/query, kept free of the obsidian import so it
// runs under `bun test`. The contract mirrors QueryRequest/QueryResponse in
// backend/main.py and frontend/src/lib/api.ts; this file must not extend it.

export type Scope = "notes" | "chats" | "all";

export interface QueryRequest {
  query: string;
  scope: Scope;
  context_nodes?: string[];
}

export interface QuerySource {
  title: string;
  source: string;
  snippet: string;
  distance: number;
}

export interface QueryResponse {
  answer: string;
  sources: QuerySource[];
  api_configured: boolean;
}

/** The slice of Obsidian's requestUrl this module needs, so tests can fake it. */
export type Transport = (req: {
  url: string;
  method: "POST";
  contentType: string;
  body: string;
  throw: false;
}) => Promise<{ status: number; text: string }>;

export class QueryError extends Error {
  constructor(message: string, readonly status = 0) {
    super(message);
    this.name = "QueryError";
  }
}

export function queryUrl(backendUrl: string): string {
  return `${backendUrl.trim().replace(/\/+$/, "")}/api/query`;
}

export function buildRequest(question: string, scope: Scope, contextNodes?: string[]): QueryRequest {
  const req: QueryRequest = { query: question.trim(), scope };
  if (contextNodes?.length) req.context_nodes = contextNodes;
  return req;
}

export async function askVault(
  transport: Transport,
  backendUrl: string,
  request: QueryRequest,
): Promise<QueryResponse> {
  if (!request.query) throw new QueryError("Type a question first.");
  const url = queryUrl(backendUrl);
  let res: { status: number; text: string };
  try {
    res = await transport({
      url,
      method: "POST",
      contentType: "application/json",
      body: JSON.stringify(request),
      throw: false,
    });
  } catch {
    throw new QueryError(`Night Atlas backend unreachable at ${url}. Is uvicorn running?`);
  }
  let body: unknown;
  try {
    body = JSON.parse(res.text);
  } catch {
    body = undefined;
  }
  if (res.status !== 200) {
    const detail = (body as { detail?: unknown } | undefined)?.detail;
    const text = typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : "";
    throw new QueryError(
      text ? `Backend error ${res.status}: ${text}` : `Backend error ${res.status}`,
      res.status,
    );
  }
  const parsed = body as Partial<QueryResponse> | undefined;
  if (!parsed || typeof parsed.answer !== "string") {
    throw new QueryError("Backend returned an unexpected response.", res.status);
  }
  return {
    answer: parsed.answer,
    sources: Array.isArray(parsed.sources) ? parsed.sources : [],
    api_configured: parsed.api_configured ?? true,
  };
}

/** Wikilink target for a vault-relative source path: drop the .md extension. */
export function linkTarget(source: string): string {
  return source.replace(/\.md$/i, "");
}

/** The answer as a Markdown callout, ready to insert into a note. */
export function toCallout(question: string, res: QueryResponse): string {
  const quote = (text: string) =>
    text
      .split("\n")
      .map((line) => (line ? `> ${line}` : ">"))
      .join("\n");
  const lines = [`> [!question] ${question.replace(/\s+/g, " ").trim()}`, quote(res.answer.trim())];
  if (res.sources.length) {
    lines.push(">", "> Sources:");
    for (const src of res.sources) lines.push(`> - [[${linkTarget(src.source)}]]`);
  }
  return lines.join("\n") + "\n";
}
