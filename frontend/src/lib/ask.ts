import type { AskHistoryEntry, AskScope, BackendQuerySource } from "./api";
import { cleanSnippet } from "./noteText";

export type AskSource = Readonly<{ title: string; source: string; snippet: string }>;

/** One answer on screen: a saved Ask-history entry, or one being streamed now. */
export type AskAnswer = Readonly<{
  question: string;
  scope: AskScope;
  body: string;
  sources: readonly AskSource[];
  /** the Ask-history id once the backend has saved it */
  historyId: string | null;
  /** epoch seconds */
  askedAt: number | null;
}>;

const MAX_SOURCES = 6;

/** Sources once per note, in the order retrieval ranked them, with a clean quote. */
export function uniqueSources(
  sources: readonly Pick<BackendQuerySource, "title" | "source" | "snippet">[],
): AskSource[] {
  const seen = new Set<string>();
  const out: AskSource[] = [];
  for (const s of sources) {
    const key = s.source || s.title;
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push({
      title: s.title || key,
      source: s.source || "",
      snippet: cleanSnippet(s.snippet || "", s.title || ""),
    });
    if (out.length >= MAX_SOURCES) break;
  }
  return out;
}

export function answerFromHistory(entry: AskHistoryEntry): AskAnswer {
  return {
    question: entry.question,
    scope: entry.scope,
    body: entry.answer || "No answer returned.",
    sources: uniqueSources(entry.sources),
    historyId: entry.id,
    askedAt: entry.asked_at,
  };
}

export function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export const SCOPES: readonly { id: AskScope; label: string; hint: string }[] = [
  { id: "notes", label: "Notes", hint: "Written vault notes only." },
  { id: "chats", label: "Chats", hint: "Exported AI chat transcripts only." },
  { id: "all", label: "All", hint: "Notes and chat transcripts together." },
];
