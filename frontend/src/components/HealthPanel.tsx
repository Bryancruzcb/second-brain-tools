"use client";

import { useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import {
  ApiError,
  fetchHealth,
  mapHealthIssues,
  type BackendHealthData,
} from "@/lib/api";
import type { HealthIssue } from "@/types";
import { GlowOutline } from "./GlowOutline";

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

type Props = {
  onOpenNote: (noteId: string, issueId: string) => void;
  sectionGlow?: boolean;
};

export function HealthPanel({ onOpenNote, sectionGlow }: Props) {
  const [issues, setIssues] = useState<HealthIssue[]>([]);
  const [stats, setStats] = useState<BackendHealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetchHealth();
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

  return (
    <GlowOutline
      id="health"
      glow={sectionGlow}
      radius={18}
      className="h-full"
    >
      <div className="card-elevated flex h-full min-h-[200px] flex-col overflow-hidden">
        <div className="flex items-center justify-between border-b border-hairline px-5 py-4">
          <div className="min-w-0">
            <h3 className="text-[16px] font-medium tracking-[-0.02em]">Repair</h3>
            <p className="mt-0.5 text-[12px] font-medium text-muted">
              {loading
                ? "Loading…"
                : error
                  ? "Backend unavailable"
                  : scanning
                    ? "Scan in progress…"
                    : totalNotes != null
                      ? `${totalNotes} notes · broken, orphans, tags`
                      : "Broken links, orphans, missing tags"}
            </p>
          </div>
          <span className="rounded-full bg-[var(--accent-softer)] px-2.5 py-1 text-[12px] font-medium text-[var(--accent)]">
            {loading ? "…" : `${toFix} to fix`}
          </span>
        </div>
        {error ? (
          <div className="px-5 py-6 text-[13px] text-[#b42318]">{error}</div>
        ) : loading ? (
          <div className="px-5 py-6 text-[13px] text-muted">Loading health…</div>
        ) : issues.length === 0 ? (
          <div className="px-5 py-6 text-[13px] text-muted">
            No broken links, orphans, or tagless notes in the latest scan.
          </div>
        ) : (
          <ul className="flex-1 divide-y divide-hairline overflow-y-auto">
            {issues.map((issue) => (
              <li key={issue.id}>
                <button
                  type="button"
                  className="group flex w-full items-start gap-3 px-5 py-3.5 text-left transition hover:bg-[#fafafa] focus-ring"
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
                    <span className="mt-1 block text-[12px] font-medium text-[var(--accent)]">
                      {issue.action}
                    </span>
                  </span>
                  <span className="mt-0.5 inline-flex shrink-0 items-center gap-0.5 text-[12px] font-medium text-muted transition group-hover:text-[var(--accent)]">
                    Open
                    <ChevronRight className="h-3.5 w-3.5" strokeWidth={2.25} />
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </GlowOutline>
  );
}
