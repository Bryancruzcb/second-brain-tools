"use client";

import { useCallback, useEffect, useRef, useState, type PointerEvent } from "react";
import {
  ApiError,
  fetchHealthCached,
  fetchNote,
  fetchRecent,
  mapHealthIssues,
  recentToNote,
} from "@/lib/api";
import { relativeDay } from "@/lib/format";
import { prefersReducedMotion } from "@/lib/scroll";
import type { HealthIssue, Note } from "@/types";

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

/** px before reel drag-scroll / pointer capture begins */
const DRAG_THRESHOLD_PX = 8;

type Props = {
  selectedId: string | null;
  repairIssueId?: string | null;
  onSelect: (id: string | null) => void;
};

export function RecentReel({
  selectedId,
  repairIssueId = null,
  onSelect,
}: Props) {
  const [reelNotes, setReelNotes] = useState<Note[]>([]);
  const [healthIssues, setHealthIssues] = useState<HealthIssue[]>([]);
  const [detailCache, setDetailCache] = useState<Record<string, Note>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const [recent, health] = await Promise.all([
          fetchRecent(),
          fetchHealthCached().catch(() => null),
        ]);
        if (cancelled) return;
        setReelNotes((recent.notes || []).map(recentToNote));
        if (health) setHealthIssues(mapHealthIssues(health.data || {}));
      } catch (e) {
        if (cancelled) return;
        setError(
          e instanceof ApiError
            ? e.message
            : "Could not load recent notes.",
        );
        setReelNotes([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // When selection is outside the recent reel (map/health), fetch into detailCache.
  // displayNotes already prepends a selected note from detailCache, so no sync setState.
  useEffect(() => {
    if (!selectedId) return;
    if (reelNotes.some((n) => n.id === selectedId)) return;
    if (detailCache[selectedId]) return;
    let cancelled = false;
    (async () => {
      try {
        const n = await fetchNote(selectedId);
        if (cancelled) return;
        const note: Note = {
          id: selectedId,
          title: n.title,
          path: selectedId,
          tags: [],
          excerpt: n.content.replace(/\s+/g, " ").trim().slice(0, 160),
          body: n.content,
          updatedAt: new Date().toISOString(),
          links: [],
          backlinks: [],
        };
        setDetailCache((c) => ({ ...c, [selectedId]: note }));
      } catch {
        /* leave reel as-is; expand may still fail gracefully */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId, reelNotes, detailCache]);

  // Load full note body when selected
  useEffect(() => {
    if (!selectedId) return;
    const cached = detailCache[selectedId];
    if (cached && cached.body && cached.body.length > 200) return;
    let cancelled = false;
    (async () => {
      setDetailLoading(true);
      try {
        const n = await fetchNote(selectedId);
        if (cancelled) return;
        const base =
          reelNotes.find((x) => x.id === selectedId) ||
          cached ||
          ({
            id: selectedId,
            title: n.title,
            path: selectedId,
            tags: [],
            excerpt: "",
            body: "",
            updatedAt: new Date().toISOString(),
            links: [],
            backlinks: [],
          } as Note);
        const note: Note = {
          ...base,
          title: n.title || base.title,
          body: n.content,
          excerpt:
            base.excerpt ||
            n.content.replace(/\s+/g, " ").trim().slice(0, 160),
        };
        setDetailCache((c) => ({ ...c, [selectedId]: note }));
        setReelNotes((prev) =>
          prev.map((x) => (x.id === selectedId ? { ...x, ...note } : x)),
        );
      } catch {
        /* keep preview */
      } finally {
        if (!cancelled) setDetailLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedId]); // eslint-disable-line react-hooks/exhaustive-deps

  const selected =
    (selectedId && (detailCache[selectedId] || reelNotes.find((n) => n.id === selectedId))) ||
    null;
  const repairIssue: HealthIssue | null =
    repairIssueId && selected
      ? (healthIssues.find((h) => h.id === repairIssueId) ?? null)
      : null;

  const displayNotes: Note[] = (() => {
    if (selected && !reelNotes.some((n) => n.id === selected.id)) {
      return [selected, ...reelNotes];
    }
    return reelNotes;
  })();

  const reelRef = useRef<HTMLDivElement>(null);
  const expandRef = useRef<HTMLDivElement>(null);
  const drag = useRef({
    active: false,
    dragging: false,
    startX: 0,
    scrollLeft: 0,
    moved: false,
  });

  useEffect(() => {
    if (!selected) return;
    const t = window.setTimeout(() => {
      expandRef.current?.scrollIntoView({
        behavior: prefersReducedMotion() ? "auto" : "smooth",
        block: "nearest",
      });
    }, 80);
    return () => window.clearTimeout(t);
  }, [selectedId, selected]);

  const onPointerDown = useCallback((e: PointerEvent) => {
    const el = reelRef.current;
    if (!el) return;
    drag.current = {
      active: true,
      dragging: false,
      startX: e.clientX,
      scrollLeft: el.scrollLeft,
      moved: false,
    };
  }, []);

  const onPointerMove = useCallback((e: PointerEvent) => {
    const el = reelRef.current;
    if (!el || !drag.current.active) return;
    const dx = e.clientX - drag.current.startX;

    if (!drag.current.dragging) {
      if (Math.abs(dx) < DRAG_THRESHOLD_PX) return;
      drag.current.dragging = true;
      drag.current.moved = true;
      try {
        el.setPointerCapture(e.pointerId);
      } catch {
        /* ignore */
      }
    }

    el.scrollLeft = drag.current.scrollLeft - dx;
  }, []);

  const onPointerUp = useCallback((e: PointerEvent) => {
    const el = reelRef.current;
    if (el && drag.current.dragging) {
      try {
        el.releasePointerCapture(e.pointerId);
      } catch {
        /* already released */
      }
    }
    drag.current.active = false;
    drag.current.dragging = false;
  }, []);

  return (
    <div id="notes" className="recent-block">
      <div className="section-heading">
        <div className="min-w-0">
          <h2 className="section-title">Recent</h2>
          {error ? (
            <p className="mt-1 text-[13px] text-[#b42318]">{error}</p>
          ) : (
            <p className="section-subtitle">
              Latest edits in the vault. Open a card to read it here.
            </p>
          )}
        </div>
      </div>

      {loading ? (
        <p className="px-1 text-[13px] text-muted">Loading recent notes…</p>
      ) : displayNotes.length === 0 && !error ? (
        <p className="px-1 text-[13px] text-muted">No recent notes from the vault.</p>
      ) : (
      <div
        ref={reelRef}
        className="reel"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {displayNotes.map((note) => (
          <NoteCard
            key={note.id}
            note={note}
            active={selectedId === note.id}
            onClick={() => {
              if (drag.current.moved) return;
              onSelect(selectedId === note.id ? null : note.id);
            }}
          />
        ))}
      </div>
      )}

      <div
        ref={expandRef}
        className="expand-panel mt-2"
        data-open={Boolean(selected)}
      >
        <div>
          {selected ? (
            <article className="card-elevated mt-2 p-6 sm:p-8">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="text-[22px] font-medium tracking-[-0.025em] text-ink">
                    {selected.title}
                  </h3>
                  <p className="mono mt-1 text-[12px] text-muted">{selected.path}</p>
                </div>
                <button
                  type="button"
                  className="rounded-full border border-hairline bg-white px-3 py-1.5 text-[13px] font-medium text-muted transition hover:text-ink focus-ring"
                  onClick={() => onSelect(null)}
                >
                  Close
                </button>
              </div>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {selected.tags.length > 0 ? (
                  selected.tags.map((t) => (
                    <span key={t} className="tag-chip">
                      {t}
                    </span>
                  ))
                ) : (
                  <span className="status-pill tagless">untagged</span>
                )}
                <span className="text-[12px] text-muted">
                  {relativeDay(selected.updatedAt)}
                </span>
                {detailLoading && (
                  <span className="text-[12px] text-muted">Loading…</span>
                )}
              </div>

              {repairIssue && (
                <div className="repair-callout mt-5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={`status-pill ${kindClass[repairIssue.kind]}`}
                    >
                      {kindLabel[repairIssue.kind]}
                    </span>
                    <span className="text-[13px] font-medium tracking-[-0.015em] text-ink">
                      Repair
                    </span>
                  </div>
                  <p className="mt-1.5 text-[13.5px] leading-snug text-ink/85">
                    {repairIssue.detail}
                  </p>
                  <p className="mt-1 text-[12.5px] font-medium text-[var(--accent-ink)]">
                    {repairIssue.action}
                  </p>
                </div>
              )}

              <div className="prose-note mt-6 whitespace-pre-wrap border-t border-hairline pt-6">
                {selected.body || "No content."}
              </div>
            </article>
          ) : (
            <div className="h-0" />
          )}
        </div>
      </div>
    </div>
  );
}

function NoteCard({
  note,
  active,
  onClick,
}: {
  note: Note;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`card group flex h-[220px] cursor-pointer flex-col p-5 text-left transition focus-ring ${
        active
          ? "border-[color-mix(in_srgb,var(--accent)_55%,var(--hairline))] shadow-[var(--shadow-md)] ring-2 ring-[var(--accent-soft)]"
          : "hover:border-[color-mix(in_srgb,var(--accent)_35%,var(--hairline))] hover:shadow-[var(--shadow-md)]"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-[12px] font-medium text-muted">
          {relativeDay(note.updatedAt)}
        </span>
        <span className="mono text-[10px] text-muted/80">
          {note.path.split("/")[0]}
        </span>
      </div>
      <h3 className="mt-3 text-[18px] font-medium leading-snug tracking-[-0.025em] text-ink">
        {note.title}
      </h3>
      <p className="mt-2 line-clamp-2 flex-1 text-[14px] leading-relaxed tracking-[-0.01em] text-muted">
        {note.excerpt}
      </p>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {note.tags.length > 0 ? (
          note.tags.slice(0, 3).map((t) => (
            <span key={t} className="tag-chip">
              {t}
            </span>
          ))
        ) : (
          <span className="status-pill tagless">untagged</span>
        )}
      </div>
    </button>
  );
}
