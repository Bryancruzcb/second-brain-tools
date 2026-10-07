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
    if (commandOpen) inputRef.current?.focus();
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

  const openHit = (hit: SearchHit) => {
    selectNote(hit.id, { view: "notes" });
    setCommandOpen(false);
    setQ("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    const total = viewJumps.length + shownHits.length;
    if (e.key === "Escape") {
      setCommandOpen(false);
      (e.target as HTMLInputElement).blur();
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

  const open = commandOpen || q.length > 0;

  return (
    <div className="relative border-b border-hairline bg-page px-4 py-2.5">
      <label className="sr-only" htmlFor="atlas-search">
        Search notes and commands
      </label>
      <div className="compose-bar max-w-3xl">
        <Search className="h-4 w-4 shrink-0 text-muted" strokeWidth={1.75} />
        <input
          id="atlas-search"
          ref={inputRef}
          type="search"
          role="combobox"
          aria-expanded={open}
          aria-controls="atlas-search-results"
          autoComplete="off"
          placeholder="Search notes or jump to a view"
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setCommandOpen(true);
          }}
          onFocus={() => setCommandOpen(true)}
          onBlur={() => {
            window.setTimeout(() => setCommandOpen(false), 120);
          }}
          onKeyDown={onKeyDown}
        />
        <span className="mono hidden shrink-0 text-[10px] text-muted sm:inline">
          ⌘K
        </span>
      </div>
      {open && (
        <ul
          id="atlas-search-results"
          role="listbox"
          className="absolute z-20 mt-1 w-[min(48rem,calc(100%-2rem))] overflow-hidden rounded-[11px] border border-hairline bg-panel shadow-[var(--shadow)]"
        >
          {viewJumps.map((id, i) => (
            <li key={id} role="option" aria-selected={active === i}>
              <button
                type="button"
                className={`flex w-full items-center justify-between px-3 py-2 text-left text-[13px] ${
                  active === i ? "bg-elevated" : ""
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
                  className={`flex w-full flex-col px-3 py-2 text-left ${
                    active === idx ? "bg-elevated" : ""
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
      )}
    </div>
  );
}
