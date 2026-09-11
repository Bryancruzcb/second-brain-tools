"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError, askQuery, composePrompts, fetchNote, type AskScope } from "@/lib/api";

type Props = {
  contextNoteId: string | null;
  onClearContext: () => void;
};

type AskAnswer = {
  query: string;
  body: string;
  sourceTitles: string[];
};

export function AskPanel({ contextNoteId, onClearContext }: Props) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<AskScope>("notes");
  const [answer, setAnswer] = useState<AskAnswer | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fetchedContext, setFetchedContext] = useState<
    { id: string; title: string } | null
  >(null);

  useEffect(() => {
    if (!contextNoteId) return;
    let cancelled = false;
    const fallback =
      contextNoteId.split("/").pop()?.replace(/\.md$/i, "") || contextNoteId;
    fetchNote(contextNoteId)
      .then((n) => {
        if (!cancelled) {
          setFetchedContext({
            id: contextNoteId,
            title: n.title || fallback,
          });
        }
      })
      .catch(() => {
        /* keep path-based title */
      });
    return () => {
      cancelled = true;
    };
  }, [contextNoteId]);

  const fallbackTitle = contextNoteId
    ? contextNoteId.split("/").pop()?.replace(/\.md$/i, "") || contextNoteId
    : null;
  const contextTitle =
    contextNoteId &&
    fetchedContext?.id === contextNoteId
      ? fetchedContext.title
      : fallbackTitle;

  const runAsk = useCallback(async () => {
    const trimmed = query.trim();
    if (!trimmed || loading) return;
    setLoading(true);
    setError(null);
    try {
      const res = await askQuery({
        query: trimmed,
        contextNodes: contextNoteId ? [contextNoteId] : undefined,
        scope,
      });
      const titles = (res.sources || [])
        .map((s) => s.title)
        .filter(Boolean)
        .filter((t, i, arr) => arr.indexOf(t) === i)
        .slice(0, 6);
      setAnswer({
        query: trimmed,
        body: res.answer || "No answer returned.",
        sourceTitles: titles,
      });
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? e.message
          : "Ask failed. Check that the backend and Ollama are running.";
      setError(msg);
      setAnswer(null);
    } finally {
      setLoading(false);
    }
  }, [query, contextNoteId, loading, scope]);

  return (
    <div>
      <div className="section-heading">
        <div className="min-w-0">
          <h2 id="ask-title" className="section-title">
            Ask
          </h2>
          <p className="section-subtitle">
            Grounded answers from Qwen, with the vault notes it drew on.
          </p>
        </div>
      </div>

      <div className="flex max-w-3xl flex-col gap-4">

          <div className="flex flex-col gap-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[12px] font-medium tracking-[-0.01em] text-ink/70">
                Search in
              </span>
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
                    className="rounded-full border px-3 py-1 text-[12px] tracking-[-0.01em] transition focus-ring"
                    style={
                      active
                        ? {
                            borderColor:
                              "color-mix(in srgb, var(--accent) 55%, var(--hairline))",
                            background:
                              "color-mix(in srgb, var(--accent) 12%, white)",
                            color: "var(--ink)",
                          }
                        : {
                            borderColor: "var(--hairline)",
                            background: "#fafafa",
                            color: "color-mix(in srgb, var(--ink) 70%, transparent)",
                          }
                    }
                    onClick={() => setScope(opt.id)}
                  >
                    {opt.label}
                  </button>
                );
              })}
            </div>
            <p className="text-[12px] leading-snug text-muted">
              {scope === "notes" &&
                "Written vault notes only (default). Switch to All if the answer may live in an exported chat."}
              {scope === "chats" &&
                "Exported AI chat transcripts only — most of the corpus."}
              {scope === "all" &&
                "Notes and chat transcripts together."}
            </p>
          </div>

          <div className="compose-bar">
            {contextNoteId && contextTitle && (
              <span className="context-chip shrink-0">
                <span className="max-w-[140px] truncate">{contextTitle}</span>
                <button
                  type="button"
                  aria-label="Remove context"
                  onClick={onClearContext}
                >
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
              placeholder="Ask…"
              aria-label="Ask"
              disabled={loading}
            />
            <button
              type="button"
              className="btn-primary h-9 shrink-0 px-3.5 text-[13px]"
              disabled={!query.trim() || loading}
              style={
                !query.trim() || loading
                  ? { opacity: 0.45, cursor: "not-allowed" }
                  : undefined
              }
              onClick={() => void runAsk()}
            >
              {loading ? "…" : "Ask"}
            </button>
          </div>

          {error && (
            <div className="ask-answer" role="alert">
              <p className="text-[13px] text-[#b42318]">{error}</p>
            </div>
          )}

          {answer && (
            <div className="ask-answer" role="status" aria-live="polite">
              <p className="whitespace-pre-wrap">{answer.body}</p>
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

          <div className="flex flex-col gap-1.5">
            {composePrompts.map((p) => (
              <button
                key={p}
                type="button"
                className="rounded-xl border border-hairline bg-[#fafafa] px-3.5 py-2.5 text-left text-[13px] tracking-[-0.01em] text-ink/85 transition hover:border-[color-mix(in_srgb,var(--accent)_40%,var(--hairline))] hover:bg-white focus-ring"
                onClick={() => setQuery(p)}
              >
                {p}
              </button>
            ))}
          </div>
      </div>
    </div>
  );
}
