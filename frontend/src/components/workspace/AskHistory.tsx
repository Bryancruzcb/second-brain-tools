"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  clearAskHistory,
  deleteAskHistoryEntry,
  fetchAskHistory,
  type AskHistoryEntry,
} from "@/lib/api";

export type { AskHistoryEntry };

function askedAgo(epochSeconds: number): string {
  const diff = Math.max(0, Date.now() / 1000 - epochSeconds);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 7 * 86400) return `${Math.floor(diff / 86400)}d ago`;
  return new Date(epochSeconds * 1000).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "America/Los_Angeles",
  });
}

/**
 * Past questions saved by the backend. Clicking one shows its saved answer
 * instantly (no new model call); "Ask again" re-runs it for a fresh answer.
 */
export function AskHistory({
  version,
  activeId,
  onSelect,
  onRerun,
}: {
  /** bump to reload, e.g. after an Ask finishes */
  version: number;
  activeId: string | null;
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
    <section className="mt-6" aria-label="Past questions">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[12px] font-medium text-muted">Past questions</h3>
        {entries.length > 0 && (
          <button type="button" className="btn btn-compact btn-ghost" onClick={() => void clearAll()}>
            Clear history
          </button>
        )}
      </div>
      {error && <p className="mb-2 text-[12px] text-[var(--danger)]">{error}</p>}
      <ul className="flex flex-col gap-1">
        {entries.map((e) => {
          const active = e.id === activeId;
          return (
            <li
              key={e.id}
              className={`flex items-center gap-2 rounded-[7px] border px-3 py-1.5 text-[13px] ${
                active
                  ? "border-[color-mix(in_srgb,var(--accent)_45%,var(--hairline))] bg-elevated"
                  : "border-hairline"
              }`}
            >
              <button
                type="button"
                className="focus-ring min-w-0 flex-1 truncate text-left text-ink/90"
                title={e.question}
                aria-pressed={active}
                onClick={() => onSelect(e)}
              >
                {e.question}
              </button>
              <span className="shrink-0 text-[11px] text-muted">{askedAgo(e.asked_at)}</span>
              <button
                type="button"
                className="btn btn-compact btn-ghost shrink-0"
                onClick={() => onRerun(e)}
              >
                Ask again
              </button>
              <button
                type="button"
                className="btn btn-compact btn-ghost shrink-0"
                aria-label={`Delete "${e.question}" from history`}
                onClick={() => void remove(e.id)}
              >
                ×
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
