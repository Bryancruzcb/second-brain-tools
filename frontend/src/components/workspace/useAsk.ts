"use client";

import { useCallback, useState } from "react";
import { ApiError, askQueryStream, type AskHistoryEntry, type AskScope } from "@/lib/api";
import { answerFromHistory, uniqueSources, type AskAnswer } from "@/lib/ask";
import { useWorkspace } from "./context";

/**
 * Ask state shared by the Notes dock and the Ask view: the composer's text and
 * scope (cells), the answer on screen (a cell held from the stream's events),
 * and `run`, the one action that calls POST /api/query/stream.
 * Returns the asked question when the stream finished, or null.
 */
export function useAsk() {
  const { askContextId } = useWorkspace();
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<AskScope>("notes");
  const [answer, setAnswer] = useState<AskAnswer | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(
    async (override?: { query: string; scope: AskScope }): Promise<string | null> => {
      const question = (override?.query ?? query).trim();
      const askScope = override?.scope ?? scope;
      if (!question || loading) return null;
      setLoading(true);
      setError(null);
      setAnswer(null);
      try {
        const full = await askQueryStream(
          {
            query: question,
            contextNodes: askContextId ? [askContextId] : undefined,
            scope: askScope,
          },
          {
            onSources: (sources) =>
              setAnswer({
                question,
                scope: askScope,
                body: "",
                sources: uniqueSources(sources),
                historyId: null,
                askedAt: Date.now() / 1000,
              }),
            onToken: (text) => setAnswer((prev) => prev && { ...prev, body: prev.body + text }),
          },
        );
        if (!full) setAnswer((prev) => prev && { ...prev, body: "No answer returned." });
        return question;
      } catch (e) {
        setError(
          e instanceof ApiError
            ? e.message
            : "Ask failed. Check that the backend and Ollama are running.",
        );
        setAnswer(null);
        return null;
      } finally {
        setLoading(false);
      }
    },
    [query, scope, askContextId, loading],
  );

  /** Show a saved answer instantly, with no new model call. */
  const show = useCallback((entry: AskHistoryEntry) => {
    setQuery(entry.question);
    setScope(entry.scope);
    setError(null);
    setAnswer(answerFromHistory(entry));
  }, []);

  return { query, setQuery, scope, setScope, answer, setAnswer, loading, error, run, show };
}
