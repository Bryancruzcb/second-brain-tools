"use client";

import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import {
  ApiError,
  fetchHealthCached,
  mapHealthIssues,
  type BackendHealthData,
} from "@/lib/api";
import type { HealthIssue } from "@/types";

const kindLabel: Record<string, string> = {
  "broken-link": "Broken",
  orphan: "Orphan",
  tagless: "Tagless",
};

const kindClass: Record<string, string> = {
  "broken-link": "broken",
  orphan: "orphan",
  tagless: "tagless",
};

/** Issues shown before "Show all"; the page scrolls, so the list should not. */
const INITIAL_VISIBLE = 8;

type Props = {
  onOpenNote: (noteId: string, issueId: string) => void;
};

export function HealthPanel({ onOpenNote }: Props) {
  const [issues, setIssues] = useState<HealthIssue[]>([]);
  const [stats, setStats] = useState<BackendHealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetchHealthCached();
        if (cancelled) return;
        setStats(res.data || null);
        setIssues(mapHealthIssues(res.data || {}));
        setScanning(Boolean(res.is_scanning));
      } catch (e) {
        if (cancelled) return;
        setError(
          e instanceof ApiError
            ? e.message
            : "Could not load vault health.",
        );
        setIssues([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const counts = {
    broken: issues.filter((h) => h.kind === "broken-link").length,
    orphan: issues.filter((h) => h.kind === "orphan").length,
    tagless: issues.filter((h) => h.kind === "tagless").length,
  };
  const toFix = counts.broken + counts.orphan + counts.tagless;
  const totalNotes = stats?.total_notes;
  const visible = expanded ? issues : issues.slice(0, INITIAL_VISIBLE);

  return (
    <div>
      <div className="section-heading">
        <div className="min-w-0">
          <h2 id="health-title" className="section-title">
            Repair
          </h2>
          <p className="section-subtitle">
            {loading
              ? "Loading…"
              : error
                ? "Backend unavailable"
                : scanning
                  ? "Scan in progress…"
                  : totalNotes != null
                    ? `${totalNotes} notes · ${counts.broken} broken · ${counts.orphan} orphans · ${counts.tagless} tagless`
                    : "Broken links, orphans, missing tags"}
          </p>
        </div>
        <span className="count-pill">
          {loading ? "…" : `${toFix} to fix`}
        </span>
      </div>

      {error ? (
        <p className="text-[13px] text-[#b42318]">{error}</p>
      ) : loading ? (
        <p className="text-[13px] text-muted">Loading health…</p>
      ) : issues.length === 0 ? (
        <p className="text-[13px] text-muted">
          No broken links, orphans, or tagless notes in the latest scan.
        </p>
      ) : (
        <>
          <ul className="issue-list divide-y divide-hairline border-y border-hairline">
            {visible.map((issue) => (
              <li key={issue.id}>
                <button
                  type="button"
                  className="group flex w-full items-start gap-3 px-2 py-3.5 text-left transition hover:bg-white focus-ring sm:px-3"
                  onClick={() => onOpenNote(issue.noteId, issue.id)}
                >
                  <span className={`status-pill mt-0.5 shrink-0 ${kindClass[issue.kind]}`}>
                    {kindLabel[issue.kind]}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13.5px] font-medium tracking-[-0.015em] text-ink">
                      {issue.title}
                    </span>
                    <span className="mt-0.5 block text-[12px] leading-snug text-muted">
                      {issue.detail}
                    </span>
                    <span className="mt-1 block text-[12px] font-medium text-[var(--accent-ink)]">
                      {issue.action}
                    </span>
                  </span>
                  <span className="mt-0.5 inline-flex shrink-0 items-center gap-0.5 text-[12px] font-medium text-muted transition group-hover:text-[var(--accent-ink)]">
                    Open
                    <ChevronRight className="h-3.5 w-3.5" strokeWidth={2.25} />
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {issues.length > INITIAL_VISIBLE && (
            <button
              type="button"
              className="show-more focus-ring"
              aria-expanded={expanded}
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? "Show fewer" : `Show all ${issues.length}`}
            </button>
          )}
        </>
      )}
    </div>
  );
}
