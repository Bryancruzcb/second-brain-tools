"use client";

import { useCallback, useEffect, useRef, type PointerEvent } from "react";
import { healthIssues, notes, recentNoteIds } from "@/data/mock";
import { relativeDay } from "@/lib/format";
import type { HealthIssue, Note } from "@/types";
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

/** px before reel drag-scroll / pointer capture begins */
const DRAG_THRESHOLD_PX = 8;

type Props = {
  selectedId: string | null;
  repairIssueId?: string | null;
  onSelect: (id: string | null) => void;
  sectionGlow?: boolean;
};

export function RecentReel({
  selectedId,
  repairIssueId = null,
  onSelect,
  sectionGlow,
}: Props) {
  const selected = selectedId ? notes.find((n) => n.id === selectedId) : null;
  const repairIssue: HealthIssue | null =
    repairIssueId && selected
      ? (healthIssues.find((h) => h.id === repairIssueId) ?? null)
      : null;

  const reelNotes: Note[] = (() => {
    const base = recentNoteIds
      .map((id) => notes.find((n) => n.id === id))
      .filter((n): n is Note => Boolean(n));
    if (selected && !base.some((n) => n.id === selected.id)) {
      return [selected, ...base];
    }
    return base;
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

  // Soft-scroll expand panel into view whenever a note opens
  useEffect(() => {
    if (!selected) return;
    const t = window.setTimeout(() => {
      expandRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }, 80);
    return () => window.clearTimeout(t);
  }, [selectedId, selected]);

  const onPointerDown = useCallback((e: PointerEvent) => {
    const el = reelRef.current;
    if (!el) return;
    // Reset each press; do NOT capture yet — wait for real drag movement
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
      // Movement exceeded threshold — start drag-scroll and capture
      drag.current.dragging = true;
      drag.current.moved = true;
      try {
        el.setPointerCapture(e.pointerId);
      } catch {
        /* ignore if capture fails */
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
    <section className="mx-auto max-w-6xl px-6 py-20">
      <GlowOutline
        id="notes"
        glow={sectionGlow}
        radius={18}
        className="rounded-[22px]"
      >
      <div className="mb-8 px-1">
        <h2 className="text-[28px] font-medium tracking-[-0.03em] text-ink sm:text-[32px]">
          Recent
        </h2>
      </div>

      <div
        ref={reelRef}
        className="reel"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {reelNotes.map((note) => (
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
                  <p className="mt-1 text-[12.5px] font-medium text-[var(--accent)]">
                    {repairIssue.action}
                  </p>
                </div>
              )}

              <div className="prose-note mt-6 border-t border-hairline pt-6">
                {selected.body}
              </div>
              {(selected.links.length > 0 || selected.backlinks.length > 0) && (
                <div className="mt-6 flex flex-wrap gap-6 border-t border-hairline pt-5 text-[13px]">
                  {selected.links.length > 0 && (
                    <div>
                      <div className="mb-2 text-[13px] text-muted">Links</div>
                      <div className="flex flex-wrap gap-2">
                        {selected.links.map((id) => {
                          const n = notes.find((x) => x.id === id);
                          return n ? (
                            <button
                              key={id}
                              type="button"
                              className="rounded-md border border-hairline bg-[#fafafa] px-2.5 py-1 text-ink/80 transition hover:border-[var(--accent)] hover:text-[var(--accent)] focus-ring"
                              onClick={() => onSelect(id)}
                            >
                              {n.title}
                            </button>
                          ) : null;
                        })}
                      </div>
                    </div>
                  )}
                  {selected.backlinks.length > 0 && (
                    <div>
                      <div className="mb-2 text-[13px] text-muted">Mentions</div>
                      <div className="flex flex-wrap gap-2">
                        {selected.backlinks.map((id) => {
                          const n = notes.find((x) => x.id === id);
                          return n ? (
                            <button
                              key={id}
                              type="button"
                              className="rounded-md border border-hairline bg-[#fafafa] px-2.5 py-1 text-ink/80 transition hover:border-[var(--accent)] hover:text-[var(--accent)] focus-ring"
                              onClick={() => onSelect(id)}
                            >
                              {n.title}
                            </button>
                          ) : null;
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </article>
          ) : (
            <div className="h-0" />
          )}
        </div>
      </div>
      </GlowOutline>
    </section>
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
