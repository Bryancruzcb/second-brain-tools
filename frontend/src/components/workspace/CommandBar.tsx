"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ArrowRight, FileText, Search } from "lucide-react";
import { ApiError, searchNotes, type SearchHit } from "@/lib/api";
import { cleanSnippet } from "@/lib/noteText";
import { TAB_ORDER, VIEW_META } from "@/lib/workspace";
import { useWorkspace } from "./context";

/**
 * The Ctrl K search palette: note search (GET /api/search, all scopes) plus
 * "Go to" jumps between views. Opens from the top bar or Ctrl K on any view.
 */
export function CommandBar() {
  const { commandOpen, setCommandOpen } = useWorkspace();
  if (!commandOpen) return null;
  return <Palette onClose={() => setCommandOpen(false)} />;
}

function Palette({ onClose }: { onClose: () => void }) {
  const { setView, selectNote } = useWorkspace();
  const inputRef = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [activeRaw, setActive] = useState(0);

  // Focus the input on open; give focus back to whatever had it on close.
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    inputRef.current?.focus();
    return () => previous?.focus?.();
  }, []);

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
  const viewJumps = TAB_ORDER.filter((id) =>
    VIEW_META[id].label.toLowerCase().includes(trimmed.toLowerCase()),
  );
  const total = viewJumps.length + shownHits.length;
  const active = Math.min(activeRaw, Math.max(0, total - 1));

  const goTo = (id: (typeof viewJumps)[number]) => {
    setView(id);
    onClose();
  };

  const openHit = (hit: SearchHit) => {
    selectNote(hit.id, { view: "notes" });
    onClose();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
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
        goTo(viewJumps[active]);
        return;
      }
      const hit = shownHits[active - viewJumps.length];
      if (hit) openHit(hit);
    }
  };

  return (
    <div
      className="palette-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="palette" role="dialog" aria-modal="true" aria-label="Search notes and views">
        <div className="composer">
          <div className="bar">
            <Search className="icon" aria-hidden strokeWidth={2} />
            <label className="sr-only" htmlFor="atlas-search">
              Search notes and views
            </label>
            <input
              id="atlas-search"
              ref={inputRef}
              type="search"
              role="combobox"
              aria-expanded="true"
              aria-controls="atlas-search-results"
              aria-activedescendant={total ? `atlas-opt-${active}` : undefined}
              autoComplete="off"
              placeholder="Search notes or jump to a view"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={onKeyDown}
            />
          </div>
        </div>
        <ul id="atlas-search-results" role="listbox" aria-label="Results" className="palette-list">
          {viewJumps.map((id, i) => (
            <li key={id} id={`atlas-opt-${i}`} role="option" aria-selected={active === i}>
              <button
                type="button"
                tabIndex={-1}
                className="cmd"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => goTo(id)}
              >
                <ArrowRight className="icon" aria-hidden strokeWidth={2} />
                <span>Go to {VIEW_META[id].label}</span>
              </button>
            </li>
          ))}
          {shownHits.map((hit, i) => {
            const idx = viewJumps.length + i;
            return (
              <li key={hit.id} id={`atlas-opt-${idx}`} role="option" aria-selected={active === idx}>
                <button
                  type="button"
                  tabIndex={-1}
                  className="cmd"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => openHit(hit)}
                >
                  <FileText className="icon" aria-hidden strokeWidth={2} />
                  <span className="hit">
                    <span className="t">{hit.title}</span>
                    <span className="s mono">{cleanSnippet(hit.snippet || "", hit.title) || hit.id}</span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
        {shownError && (
          <p className="palette-msg bad" role="alert">
            {shownError}
          </p>
        )}
        {searching && !shownError && shownHits.length === 0 && (
          <p className="palette-msg" role="status">
            No matching notes.
          </p>
        )}
      </div>
    </div>
  );
}
