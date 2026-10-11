"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CircleAlert, FileText, LocateFixed, MessageSquareText, RotateCcw, X } from "lucide-react";
import {
  ApiError,
  composePrompts,
  deleteAskHistoryEntry,
  fetchAskHistory,
  searchNotes,
  type SearchHit,
} from "@/lib/api";
import { answerFromHistory } from "@/lib/ask";
import { cleanSnippet } from "@/lib/noteText";
import { AnswerBlock, AskComposer } from "./AskParts";
import { useAsk } from "./useAsk";

type Latest = { status: "loading" } | { status: "error" } | { status: "ready" };
type Find =
  | { status: "idle" }
  | { status: "loading"; query: string }
  | { status: "ready"; query: string; hits: SearchHit[] }
  | { status: "error"; query: string; message: string };

/**
 * Ask as a command bar under the chart (Linear's command menu): the latest
 * answer with numbered sources above, suggested questions or Find results in
 * the middle, the input at the bottom. The full history stays on the Ask tab.
 */
export function AskDock({
  nowMs,
  chartIds,
  onSources,
  onShowSource,
}: {
  nowMs: number;
  /** notes drawn on the chart */
  chartIds: ReadonlySet<string>;
  /** the sources of the answer on screen, for the chart's bracket and the reading pane */
  onSources: (ids: ReadonlySet<string>) => void;
  onShowSource: (id: string, onChart: boolean) => void;
}) {
  const ask = useAsk();
  const { answer, setAnswer, run, loading, error, query, setQuery, scope } = ask;
  const [latest, setLatest] = useState<Latest>({ status: "loading" });
  const [find, setFind] = useState<Find>({ status: "idle" });
  const inputRef = useRef<HTMLInputElement>(null);

  const loadLatest = useCallback(async () => {
    try {
      const res = await fetchAskHistory(1);
      const entry = res.entries?.[0];
      setAnswer(entry ? answerFromHistory(entry) : null);
      setLatest({ status: "ready" });
    } catch {
      setLatest({ status: "error" });
    }
  }, [setAnswer]);

  useEffect(() => {
    let cancelled = false;
    fetchAskHistory(1)
      .then((res) => {
        if (cancelled) return;
        const entry = res.entries?.[0];
        setAnswer(entry ? answerFromHistory(entry) : null);
        setLatest({ status: "ready" });
      })
      .catch(() => {
        if (!cancelled) setLatest({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [setAnswer]);

  const sourceKey = answer ? answer.sources.map((s) => s.source).join("\n") : "";
  useEffect(() => {
    onSources(new Set(sourceKey ? sourceKey.split("\n") : []));
  }, [sourceKey, onSources]);

  /** Ask, then pick up the saved entry's id so Remove works on the new answer. */
  const askNow = async (override?: { query: string; scope: typeof scope }) => {
    setFind({ status: "idle" });
    const asked = await run(override);
    if (!asked) return;
    try {
      const res = await fetchAskHistory(1);
      const entry = res.entries?.[0];
      if (entry && entry.question.trim() === asked) {
        setAnswer((prev) =>
          prev && prev.historyId === null && prev.question === asked
            ? { ...prev, historyId: entry.id, askedAt: entry.asked_at }
            : prev,
        );
      }
    } catch {
      /* the answer stays on screen without Remove */
    }
  };

  const findNow = async () => {
    const q = query.trim();
    if (!q) return;
    setFind({ status: "loading", query: q });
    try {
      const res = await searchNotes(q, scope);
      setFind({ status: "ready", query: q, hits: res.results || [] });
    } catch (e) {
      setFind({ status: "error", query: q, message: e instanceof ApiError ? e.message : "Search failed." });
    }
  };

  const remove = async (id: string) => {
    try {
      await deleteAskHistoryEntry(id);
    } catch {
      /* reloading shows what the backend kept */
    }
    await loadLatest();
  };

  const writing = loading;

  return (
    <section className="dock" aria-label="Ask and find">
      {error ? (
        <div className="answer" role="alert">
          <p className="dock-head mono">
            <CircleAlert className="icon" aria-hidden strokeWidth={2} style={{ color: "var(--danger)" }} />
            Ask did not finish
          </p>
          <p className="answer-text quiet">{error}</p>
        </div>
      ) : answer ? (
        <AnswerBlock
          answer={answer}
          heading={answer.historyId || !writing ? "Latest answer" : "Answering"}
          idPrefix="dock"
          writing={writing}
          nowMs={Math.max(nowMs, (answer.askedAt ?? 0) * 1000)}
          sourceAction={(s) => {
            const onChart = chartIds.has(s.source);
            return (
              <button type="button" className="btn" onClick={() => onShowSource(s.source, onChart)}>
                {onChart ? (
                  <LocateFixed className="icon" aria-hidden strokeWidth={2} />
                ) : (
                  <FileText className="icon" aria-hidden strokeWidth={2} />
                )}
                {onChart ? "Show on chart" : "Open note"}
              </button>
            );
          }}
          actions={
            !writing && (
              <>
                <button
                  type="button"
                  className="btn btn-quiet"
                  onClick={() => void askNow({ query: answer.question, scope: answer.scope })}
                >
                  <RotateCcw className="icon" aria-hidden strokeWidth={2} />
                  Ask again
                </button>
                {answer.historyId && (
                  <button type="button" className="btn btn-quiet" onClick={() => void remove(answer.historyId!)}>
                    <X className="icon" aria-hidden strokeWidth={2} />
                    Remove
                  </button>
                )}
              </>
            )
          }
        />
      ) : writing ? (
        <div className="answer" aria-busy="true">
          <p className="dock-head mono">
            <MessageSquareText className="icon" aria-hidden strokeWidth={2} />
            Looking through your notes…
          </p>
          <span className="sk" style={{ width: "95%", marginTop: 14 }} />
          <span className="sk" style={{ width: "60%", margin: "8px 0 14px" }} />
        </div>
      ) : latest.status === "loading" ? (
        <div className="answer" aria-busy="true" aria-label="Loading the latest answer">
          <span className="sk" style={{ width: "40%", height: 12 }} />
          <span className="sk" style={{ width: "70%", height: 18, marginTop: 14 }} />
          <span className="sk" style={{ width: "95%", marginTop: 12 }} />
          <span className="sk" style={{ width: "60%", marginTop: 8 }} />
          <span className="sk" style={{ width: "100%", height: 56, margin: "18px 0 14px" }} />
        </div>
      ) : latest.status === "error" ? (
        <div className="answer">
          <p className="dock-head mono">
            <CircleAlert className="icon" aria-hidden strokeWidth={2} />
            Past answers could not load
          </p>
          <p className="answer-text quiet">Answers need the backend. Start it, then ask again.</p>
        </div>
      ) : (
        <div className="answer">
          <p className="dock-head mono">
            <MessageSquareText className="icon" aria-hidden strokeWidth={2} />
            No questions yet
          </p>
          <p className="answer-text quiet">Ask something below. The answer, and the notes it came from, show up here.</p>
        </div>
      )}

      {find.status === "idle" ? (
        <div className="cmds">
          <p className="cmds-label mono">Try asking</p>
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {composePrompts.map((p) => (
              <li key={p}>
                <button
                  type="button"
                  className="cmd"
                  onClick={() => {
                    setQuery(p);
                    inputRef.current?.focus();
                  }}
                >
                  <MessageSquareText className="icon" aria-hidden strokeWidth={2} />
                  {p}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <div className="cmds" aria-live="polite">
          <p className="cmds-label mono" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>Notes matching “{find.query}”</span>
            <button type="button" className="btn btn-quiet" onClick={() => setFind({ status: "idle" })}>
              Clear
            </button>
          </p>
          {find.status === "loading" ? (
            <p className="palette-msg">Searching…</p>
          ) : find.status === "error" ? (
            <p className="palette-msg bad" role="alert">
              {find.message}
            </p>
          ) : find.hits.length === 0 ? (
            <p className="palette-msg">No matching notes.</p>
          ) : (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {find.hits.map((hit) => (
                <li key={hit.id}>
                  <button
                    type="button"
                    className="cmd"
                    onClick={() => onShowSource(hit.id, false)}
                  >
                    <FileText className="icon" aria-hidden strokeWidth={2} />
                    <span className="hit">
                      <span className="t">{hit.title}</span>
                      <span className="s mono">{cleanSnippet(hit.snippet || "", hit.title) || hit.id}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <AskComposer
        inputId="dock-q"
        inputRef={inputRef}
        query={query}
        onQuery={setQuery}
        scope={scope}
        onScope={ask.setScope}
        loading={loading}
        onAsk={() => void askNow()}
        onFind={() => void findNow()}
      />
    </section>
  );
}
