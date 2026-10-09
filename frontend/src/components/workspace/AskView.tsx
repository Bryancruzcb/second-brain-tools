"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, askQueryStream, composePrompts, fetchNote, type AskScope } from "@/lib/api";
import { useWorkspace } from "./context";

type AskAnswer = {
  query: string;
  body: string;
  sourceTitles: string[];
};

export function AskView() {
  const { askContextId, setAskContextId } = useWorkspace();
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<AskScope>("notes");
  const [answer, setAnswer] = useState<AskAnswer | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fetchedContext, setFetchedContext] = useState<{
    id: string;
    title: string;
  } | null>(null);

  useEffect(() => {
    if (!askContextId) return;
    let cancelled = false;
    const fallback =
      askContextId.split("/").pop()?.replace(/\.md$/i, "") || askContextId;
    fetchNote(askContextId)
      .then((n) => {
        if (!cancelled) {
          setFetchedContext({ id: askContextId, title: n.title || fallback });
        }
      })
      .catch(() => {
        /* keep path-based title */
      });
    return () => {
      cancelled = true;
    };
  }, [askContextId]);

  const fallbackTitle = askContextId
    ? askContextId.split("/").pop()?.replace(/\.md$/i, "") || askContextId
    : null;
  const contextTitle =
    askContextId && fetchedContext?.id === askContextId
      ? fetchedContext.title
      : fallbackTitle;

  const runAsk = useCallback(async () => {
    const trimmed = query.trim();
    if (!trimmed || loading) return;
    setLoading(true);
    setError(null);
    setAnswer(null);
    try {
      const full = await askQueryStream(
        {
          query: trimmed,
          contextNodes: askContextId ? [askContextId] : undefined,
          scope,
        },
        {
          onSources: (sources) => {
            const titles = sources
              .map((s) => s.title)
              .filter(Boolean)
              .filter((t, i, arr) => arr.indexOf(t) === i)
              .slice(0, 6);
            setAnswer({ query: trimmed, body: "", sourceTitles: titles });
          },
          onToken: (text) =>
            setAnswer((prev) => prev && { ...prev, body: prev.body + text }),
        },
      );
      if (!full) {
        setAnswer((prev) => prev && { ...prev, body: "No answer returned." });
      }
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : "Ask failed. Check that the backend and Ollama are running.",
      );
      setAnswer(null);
    } finally {
      setLoading(false);
    }
  }, [query, askContextId, loading, scope]);

  return (
    <div className="mx-auto flex min-h-0 w-full max-w-3xl flex-1 flex-col overflow-y-auto px-5 py-6">
      <header className="mb-5">
        <h2 className="text-[15px] font-medium tracking-[-0.02em]">Ask</h2>
        <p className="mt-0.5 text-[12px] text-muted">
          Grounded in the local vault. Nothing is sent to a hosted model.
        </p>
      </header>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <span className="text-[12px] text-muted">Search in</span>
        {(
          [
            { id: "notes", label: "Notes" },
            { id: "chats", label: "Chats" },
            { id: "all", label: "All" },
          ] as const
        ).map((opt) => {
          const active = scope === opt.id;
          return (
            <button
              key={opt.id}
              type="button"
              aria-pressed={active}
              className={`btn btn-compact ${active ? "btn-secondary" : "btn-ghost"}`}
              onClick={() => setScope(opt.id)}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
      <p className="mb-4 text-[12px] text-muted">
        {scope === "notes" && "Written vault notes only."}
        {scope === "chats" && "Exported AI chat transcripts only."}
        {scope === "all" && "Notes and chat transcripts together."}
      </p>

      <div className="compose-bar">
        {askContextId && contextTitle && (
          <span className="context-chip shrink-0">
            <span className="max-w-[160px] truncate">{contextTitle}</span>
            <button type="button" aria-label="Remove context" onClick={() => setAskContextId(null)}>
              ×
            </button>
          </span>
        )}
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              void runAsk();
            }
          }}
          placeholder="Ask the vault…"
          aria-label="Ask"
          disabled={loading}
        />
        <button
          type="button"
          className="btn btn-primary"
          disabled={!query.trim() || loading}
          onClick={() => void runAsk()}
        >
          {loading ? "Asking…" : "Ask"}
        </button>
      </div>

      {error && (
        <div className="ask-answer mt-4" role="alert">
          <p className="text-[13px] text-[var(--danger)]">{error}</p>
        </div>
      )}

      {answer && (
        <div className="ask-answer mt-4" role="status" aria-live="polite">
          <p className="whitespace-pre-wrap">
            {answer.body || (loading ? "Writing…" : "")}
          </p>
          {answer.sourceTitles.length > 0 && (
            <div className="ask-sources">
              <span className="ask-sources-label">
                {answer.sourceTitles.length === 1 ? "Source" : "Sources"}
              </span>
              {answer.sourceTitles.map((t) => (
                <span key={t} className="tag-chip">
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="mt-5 flex flex-col gap-1.5">
        {composePrompts.map((p) => (
          <button
            key={p}
            type="button"
            className="focus-ring rounded-[7px] border border-hairline bg-elevated px-3 py-2 text-left text-[13px] text-ink/90 hover:border-[color-mix(in_srgb,var(--accent)_35%,var(--hairline))]"
            onClick={() => setQuery(p)}
          >
            {p}
          </button>
        ))}
      </div>
    </div>
  );
}
