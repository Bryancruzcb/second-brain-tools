"use client";

import { useCallback, useEffect, useState } from "react";
import { RotateCcw, X } from "lucide-react";
import {
  ApiError,
  clearAskHistory,
  deleteAskHistoryEntry,
  fetchAskHistory,
  type AskHistoryEntry,
} from "@/lib/api";
import { askedAgo } from "@/lib/format";

export type { AskHistoryEntry };

/**
 * Past questions saved by the backend. Clicking one shows its saved answer
 * instantly (no new model call); "Ask again" re-runs it for a fresh answer.
 */
export function AskHistory({
  version,
  activeId,
  nowMs,
  onSelect,
  onRerun,
}: {
  /** bump to reload, e.g. after an Ask finishes */
  version: number;
  activeId: string | null;
  nowMs: number;
  onSelect: (entry: AskHistoryEntry) => void;
  onRerun: (entry: AskHistoryEntry) => void;
}) {
  const [entries, setEntries] = useState<AskHistoryEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetchAskHistory(200)
      .then((res) => {
        if (cancelled) return;
        setEntries(res.entries || []);
        setError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof ApiError ? e.message : "Could not load history.");
      });
    return () => {
      cancelled = true;
    };
  }, [version, reloads]);

  const remove = useCallback(async (id: string) => {
    try {
      await deleteAskHistoryEntry(id);
    } catch {
      /* reload shows the truth either way */
    }
    setReloads((n) => n + 1);
  }, []);

  const clearAll = useCallback(async () => {
    if (!window.confirm("Clear all saved questions and answers?")) return;
    try {
      await clearAskHistory();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not clear history.");
    }
    setReloads((n) => n + 1);
  }, []);

  if (!entries.length && !error) return null;

  return (
    <section className="dock" aria-labelledby="past-h">
      <div className="pane-head" style={{ padding: "14px 16px 6px" }}>
        <h2 id="past-h" style={{ fontSize: 14 }}>
          Past questions
        </h2>
        {entries.length > 0 && (
          <button type="button" className="btn btn-quiet" onClick={() => void clearAll()}>
            Clear history
          </button>
        )}
      </div>
      {error && (
        <p className="palette-msg bad" role="alert">
          {error}
        </p>
      )}
      <ul style={{ listStyle: "none", margin: 0, padding: "0 8px 8px" }}>
        {entries.map((e) => {
          const active = e.id === activeId;
          return (
            <li key={e.id} className={`history-item${active ? " active" : ""}`}>
              <button
                type="button"
                className="q focus-ring"
                title={e.question}
                aria-pressed={active}
                onClick={() => onSelect(e)}
              >
                {e.question}
              </button>
              <span className="when mono num">{askedAgo(e.asked_at, nowMs)}</span>
              <button type="button" className="btn btn-quiet" onClick={() => onRerun(e)}>
                <RotateCcw className="icon" aria-hidden strokeWidth={2} />
                Ask again
              </button>
              <button
                type="button"
                className="btn btn-quiet btn-icon"
                aria-label={`Delete "${e.question}" from history`}
                onClick={() => void remove(e.id)}
              >
                <X className="icon" aria-hidden strokeWidth={2} />
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
