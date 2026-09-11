"use client";

import { useEffect, useState } from "react";
import { ApiError, fetchRecent, recentToNote } from "@/lib/api";
import { relativeDay } from "@/lib/format";
import type { Note } from "@/types";
import { useWorkspace } from "./context";
import { NoteInspector } from "./NoteInspector";

export function NotesView() {
  const { selectedNoteId, selectNote } = useWorkspace();
  const [notes, setNotes] = useState<Note[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const res = await fetchRecent();
        if (cancelled) return;
        setNotes((res.notes || []).map(recentToNote));
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof ApiError ? e.message : "Could not load recent notes.");
        setNotes([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex min-h-0 min-w-0 flex-1">
      <section className="flex w-[min(22rem,40%)] shrink-0 flex-col border-r border-hairline max-md:w-full max-md:border-r-0">
        <header className="border-b border-hairline px-4 py-3">
          <h2 className="text-[15px] font-medium tracking-[-0.02em]">Recent</h2>
          <p className="mt-0.5 text-[12px] text-muted">
            {loading
              ? "Loading…"
              : error
                ? "Backend unavailable"
                : `${notes.length} notes`}
          </p>
        </header>
        {error ? (
          <p className="px-4 py-6 text-[13px] text-[var(--danger)]">{error}</p>
        ) : loading ? (
          <p className="px-4 py-6 text-[13px] text-muted">Loading recent notes…</p>
        ) : notes.length === 0 ? (
          <p className="px-4 py-6 text-[13px] text-muted">
            No recent notes. Start the backend or wait for the index.
          </p>
        ) : (
          <ul className="min-h-0 flex-1 overflow-y-auto">
            {notes.map((note) => {
              const active = selectedNoteId === note.id;
              return (
                <li key={note.id}>
                  <button
                    type="button"
                    className={`focus-ring w-full border-l-2 px-4 py-3 text-left ${
                      active
                        ? "border-[var(--accent)] bg-elevated"
                        : "border-transparent hover:bg-elevated"
                    }`}
                    onClick={() =>
                      selectNote(active ? null : note.id, { repairIssueId: null })
                    }
                  >
                    <span className="mono text-[10px] text-muted">
                      {relativeDay(note.updatedAt)}
                    </span>
                    <span className="mt-0.5 block truncate text-[13.5px] font-medium">
                      {note.title}
                    </span>
                    <span className="mt-0.5 line-clamp-2 text-[12px] text-muted">
                      {note.excerpt}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </section>
      <div className="min-w-0 flex-1 bg-panel max-md:hidden">
        <NoteInspector />
      </div>
      {selectedNoteId && (
        <div className="absolute inset-0 z-10 bg-panel md:hidden">
          <NoteInspector onClose={() => selectNote(null, { repairIssueId: null })} />
        </div>
      )}
    </div>
  );
}
