"use client";

import { useCallback, useEffect, useState } from "react";
import { CircleAlert, CircleCheck, ScanSearch } from "lucide-react";
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
      <section className="flex w-[min(28rem,42%)] shrink-0 flex-col border-r border-hairline bg-panel max-md:w-full max-md:border-r-0">
        <header className="view-head">
          <div>
            <h1>Repair</h1>
            <p className="sub" role="status">
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
            className="btn"
            disabled={scanning}
            onClick={() => void onScan()}
          >
            <ScanSearch className="icon" aria-hidden strokeWidth={2} />
            {scanning ? "Scanning…" : "Scan"}
          </button>
        </header>
        {error ? (
          <div className="pane-msg bad" style={{ marginTop: 20 }}>
            <CircleAlert aria-hidden strokeWidth={2} />
            <strong>Vault health could not load.</strong>
            {error}
          </div>
        ) : loading ? (
          <ul className="m-0 list-none p-0" aria-busy="true" aria-label="Loading vault health">
            {Array.from({ length: 6 }, (_, i) => (
              <li key={i} className="issue">
                <span className="sk" style={{ width: 64, height: 22 }} />
                <span className="min-w-0 flex-1">
                  <span className="sk" style={{ width: "55%" }} />
                  <span className="sk" style={{ width: "85%", height: 12, marginTop: 8 }} />
                </span>
              </li>
            ))}
          </ul>
        ) : issues.length === 0 ? (
          <div className="pane-msg" style={{ marginTop: 20 }}>
            <CircleCheck aria-hidden strokeWidth={2} style={{ color: "var(--success)" }} />
            <strong>Nothing to fix.</strong>
            No broken links, orphans, or tagless notes in the latest scan.
          </div>
        ) : (
          <ul className="m-0 min-h-0 flex-1 list-none divide-y divide-hairline overflow-y-auto p-0">
            {issues.map((issue) => {
              const active = repairIssueId === issue.id;
              return (
                <li key={issue.id}>
                  <button
                    type="button"
                    className="issue focus-ring"
                    aria-current={active ? "true" : undefined}
                    onClick={() =>
                      selectNote(issue.noteId, { repairIssueId: issue.id })
                    }
                  >
                    <span className={`status-pill mt-0.5 shrink-0 ${kindClass[issue.kind]}`}>
                      {kindLabel[issue.kind]}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="t">{issue.title}</span>
                      <span className="s">{issue.detail}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>
      <div className="min-w-0 flex-1 bg-page max-md:hidden">
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
