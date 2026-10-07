"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  fetchHealth,
  mapHealthIssues,
  scanHealth,
  type BackendHealthData,
} from "@/lib/api";
import type { HealthIssue } from "@/types";
import { useWorkspace } from "./context";
import { NoteInspector } from "./NoteInspector";

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

export function RepairView() {
  const { selectedNoteId, selectNote, repairIssueId } = useWorkspace();
  const [issues, setIssues] = useState<HealthIssue[]>([]);
  const [stats, setStats] = useState<BackendHealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scanning, setScanning] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await fetchHealth();
      setStats(res.data || null);
      setIssues(mapHealthIssues(res.data || {}));
      setScanning(Boolean(res.is_scanning));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load vault health.");
      setIssues([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetchHealth();
        if (cancelled) return;
        setStats(res.data || null);
        setIssues(mapHealthIssues(res.data || {}));
        setScanning(Boolean(res.is_scanning));
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof ApiError ? e.message : "Could not load vault health.");
        setIssues([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!scanning) return;
    const id = window.setInterval(() => void load(), 2500);
    return () => window.clearInterval(id);
  }, [scanning, load]);

  const onScan = async () => {
    setScanning(true);
    try {
      await scanHealth();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not start scan.");
      setScanning(false);
    }
  };

  const counts = {
    broken: issues.filter((h) => h.kind === "broken-link").length,
    orphan: issues.filter((h) => h.kind === "orphan").length,
    tagless: issues.filter((h) => h.kind === "tagless").length,
  };
  const toFix = counts.broken + counts.orphan + counts.tagless;
  const activeIssue = issues.find((h) => h.id === repairIssueId) ?? null;

  return (
    <div className="flex min-h-0 min-w-0 flex-1">
      <section className="flex w-[min(26rem,42%)] shrink-0 flex-col border-r border-hairline max-md:w-full">
        <header className="flex items-start justify-between gap-3 border-b border-hairline px-4 py-3">
          <div>
            <h2 className="text-[15px] font-medium tracking-[-0.02em]">Repair</h2>
            <p className="mt-0.5 text-[12px] text-muted">
              {loading
                ? "Loading…"
                : error
                  ? "Backend unavailable"
                  : scanning
                    ? "Scan in progress…"
                    : stats?.total_notes != null
                      ? `${stats.total_notes} notes · ${toFix} to fix`
                      : `${toFix} to fix`}
            </p>
          </div>
          <button
            type="button"
            className="btn btn-secondary btn-compact"
            disabled={scanning}
            onClick={() => void onScan()}
          >
            {scanning ? "Scanning…" : "Scan"}
          </button>
        </header>
        {error ? (
          <p className="px-4 py-6 text-[13px] text-[var(--danger)]">{error}</p>
        ) : loading ? (
          <p className="px-4 py-6 text-[13px] text-muted">Loading health…</p>
        ) : issues.length === 0 ? (
          <p className="px-4 py-6 text-[13px] text-muted">
            No broken links, orphans, or tagless notes in the latest scan.
          </p>
        ) : (
          <ul className="min-h-0 flex-1 divide-y divide-hairline overflow-y-auto">
            {issues.map((issue) => {
              const active = repairIssueId === issue.id;
              return (
                <li key={issue.id}>
                  <button
                    type="button"
                    className={`focus-ring flex w-full items-start gap-3 px-4 py-3 text-left ${
                      active ? "bg-elevated" : "hover:bg-elevated"
                    }`}
                    onClick={() =>
                      selectNote(issue.noteId, { repairIssueId: issue.id })
                    }
                  >
                    <span className={`status-pill mt-0.5 shrink-0 ${kindClass[issue.kind]}`}>
                      {kindLabel[issue.kind]}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13.5px] font-medium">
                        {issue.title}
                      </span>
                      <span className="mt-0.5 block text-[12px] text-muted">
                        {issue.detail}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>
      <div className="min-w-0 flex-1 bg-panel max-md:hidden">
        <NoteInspector repairIssue={activeIssue} />
      </div>
      {selectedNoteId && (
        <div className="absolute inset-0 z-10 bg-panel md:hidden">
          <NoteInspector
            repairIssue={activeIssue}
            onClose={() => selectNote(null, { repairIssueId: null })}
          />
        </div>
      )}
    </div>
  );
}
