/** What /api/ready said last, or that the backend could not be reached. null = not asked yet. */
export type ReadyState = {
  ready: boolean;
  components: Record<string, boolean>;
  reachable: boolean;
} | null;

export type IndexStatus = {
  tone: "ok" | "wait" | "bad";
  text: string;
  /** one line per retrieval component, for a tooltip */
  detail?: string;
};

/** Plain words for the index state, shown in the top bar and the Notes lead line. */
export function indexStatus(ready: ReadyState): IndexStatus {
  if (!ready) return { tone: "wait", text: "Checking the backend…" };
  if (!ready.reachable) return { tone: "bad", text: "Backend unreachable" };
  const detail = Object.entries(ready.components)
    .map(([k, v]) => `${k}: ${v ? "on" : "off"}`)
    .join("\n");
  return ready.ready
    ? { tone: "ok", text: "Index ready", detail }
    : { tone: "wait", text: "Loading retrieval…", detail };
}
