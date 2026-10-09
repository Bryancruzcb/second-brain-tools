"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Search } from "lucide-react";
import { ApiError, searchNotes, type SearchHit } from "@/lib/api";
import { VIEW_META, type ViewId } from "@/lib/workspace";
import { useWorkspace } from "./context";

export function CommandBar() {
  const { setView, selectNote, commandOpen, setCommandOpen } = useWorkspace();
  const inputRef = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState(0);

  useEffect(() => {
    if (!commandOpen) return;
    // Return focus to whatever opened the dialog (e.g. the sidebar button).
    const opener = document.activeElement as HTMLElement | null;
    inputRef.current?.focus();
    return () => opener?.focus?.();
  }, [commandOpen]);

  const trimmed = q.trim();
  const searching = trimmed.length >= 2;

  useEffect(() => {
    if (!searching) return;
    let cancelled = false;
    const t = window.setTimeout(async () => {
      try {
        const res = await searchNotes(trimmed, "all");
        if (!cancelled) {
          setHits(res.results || []);
          setError(null);
          setActive(0);
        }
      } catch (e) {
        if (!cancelled) {
          setHits([]);
          setError(e instanceof ApiError ? e.message : "Search failed.");
        }
      }
    }, 180);
    return () => {
      cancelled = true;
      window.clearTimeout(t);
    };
  }, [searching, trimmed]);

  const shownHits = searching ? hits : [];
  const shownError = searching ? error : null;

  const viewJumps = (Object.keys(VIEW_META) as ViewId[]).filter((id) =>
    VIEW_META[id].label.toLowerCase().includes(q.trim().toLowerCase() || ""),
  );

  const close = () => {
    setCommandOpen(false);
    setQ("");
  };

  const openHit = (hit: SearchHit) => {
    selectNote(hit.id, { view: "notes" });
    close();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    const total = viewJumps.length + shownHits.length;
    if (e.key === "Escape") {
      e.preventDefault();
      close();
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(total - 1, i + 1));
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    }
    if (e.key === "Enter") {
      e.preventDefault();
      if (active < viewJumps.length) {
        setView(viewJumps[active]);
        setCommandOpen(false);
        setQ("");
        return;
      }
      const hit = shownHits[active - viewJumps.length];
      if (hit) openHit(hit);
    }
  };

  // Interim search dialog opened by the sidebar button and ⌘K. The full ⌘K
  // palette (sections, highlights, Ask/New note actions) replaces it later.
  if (!commandOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-center bg-black/55 px-4 pt-[12vh]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Search notes and views"
        className="relative h-fit w-full max-w-[640px] rounded-card border border-dialog bg-surface p-2 shadow-[var(--shadow-dialog)]"
      >
      <label className="sr-only" htmlFor="atlas-search">
        Search notes and commands
      </label>
      <div className="flex h-[52px] items-center gap-3 px-3">
        <Search aria-hidden className="h-[18px] w-[18px] shrink-0 text-tertiary" strokeWidth={1.75} />
        <input
          id="atlas-search"
          ref={inputRef}
          type="search"
          role="combobox"
          aria-expanded
          aria-controls="atlas-search-results"
          autoComplete="off"
          placeholder="Search notes or jump to a view"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={onKeyDown}
          className="min-w-0 flex-1 bg-transparent text-[17px] text-primary outline-none placeholder:text-tertiary"
        />
        <kbd className="kbd">esc</kbd>
      </div>
      <ul
          id="atlas-search-results"
          role="listbox"
          className="max-h-[400px] overflow-y-auto border-t border-divider pt-1"
        >
          {viewJumps.map((id, i) => (
            <li key={id} role="option" aria-selected={active === i}>
              <button
                type="button"
                className={`flex w-full items-center justify-between min-h-11 rounded-control px-3 py-2 text-left text-[14px] ${
                  active === i ? "bg-active" : "hover:bg-hover"
                }`}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => {
                  setView(id);
                  setCommandOpen(false);
                  setQ("");
                }}
              >
                <span>Go to {VIEW_META[id].label}</span>
                <span className="mono text-[10px] text-muted">
                  {VIEW_META[id].description}
                </span>
              </button>
            </li>
          ))}
          {shownError && (
            <li className="px-3 py-2 text-[12px] text-[var(--danger)]">{shownError}</li>
          )}
          {shownHits.map((hit, i) => {
            const idx = viewJumps.length + i;
            return (
              <li key={hit.id} role="option" aria-selected={active === idx}>
                <button
                  type="button"
                  className={`flex min-h-11 w-full flex-col rounded-control px-3 py-2 text-left ${
                    active === idx ? "bg-active" : "hover:bg-hover"
                  }`}
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => openHit(hit)}
                >
                  <span className="text-[13px] font-medium">{hit.title}</span>
                  <span className="mono truncate text-[11px] text-muted">
                    {hit.snippet || hit.id}
                  </span>
                </button>
              </li>
            );
          })}
          {searching && !shownError && shownHits.length === 0 && (
            <li className="px-3 py-2 text-[12px] text-muted">No matching notes.</li>
          )}
        </ul>
      </div>
    </div>
  );
}
