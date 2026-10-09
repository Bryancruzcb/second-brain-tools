"use client";

import { useEffect, useState } from "react";
import { ArrowUpRight, Sparkles } from "lucide-react";
import { ApiError, fetchNote } from "@/lib/api";

export type InspectorNeighbor = {
  id: string;
  title: string;
  folder: string;
  color: string;
  chat: boolean;
};

type Props = {
  id: string;
  title: string;
  folder: string;
  color: string;
  linkedNotes: number;
  neighbors: InspectorNeighbor[];
  onSelect: (id: string) => void;
  onOpen: () => void;
  onAsk: () => void;
};

/** First readable lines of a note: no frontmatter, no title heading. */
function previewText(content: string, title: string): string {
  let text = content.replace(/^\uFEFF/, "");
  if (text.startsWith("---")) {
    const end = text.indexOf("\n---", 3);
    if (end > -1) text = text.slice(end + 4);
  }
  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  if (lines[0] && /^#\s+/.test(lines[0])) {
    const heading = lines[0].replace(/^#\s+/, "").trim();
    if (heading.toLowerCase() === title.toLowerCase() || lines.length > 1) lines.shift();
  }
  return lines
    .join(" ")
    .replace(/!\[\[[^\]]*\]\]/g, "")
    .replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, "$2")
    .replace(/\[\[([^\]]+)\]\]/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[*_`>#]+/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 420);
}

export function MapInspector({
  id,
  title,
  folder,
  color,
  linkedNotes,
  neighbors,
  onSelect,
  onOpen,
  onAsk,
}: Props) {
  const [preview, setPreview] = useState<{
    id: string;
    text: string | null;
    error: string | null;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchNote(id)
      .then((n) => {
        if (!cancelled)
          setPreview({ id, text: previewText(n.content || "", title), error: null });
      })
      .catch((e) => {
        if (!cancelled)
          setPreview({
            id,
            text: null,
            error: e instanceof ApiError ? e.message : "Could not load a preview.",
          });
      });
    return () => {
      cancelled = true;
    };
  }, [id, title]);

  const current = preview?.id === id ? preview : null;

  return (
    <aside
      aria-label="Selected note"
      className="flex min-h-0 w-full flex-1 flex-col overflow-y-auto rounded-card border border-divider bg-panel p-5"
    >
      <div className="flex items-center justify-between gap-2">
        <span
          className="inline-flex h-7 max-w-[180px] items-center gap-2 rounded-chip px-2.5 text-[12px] font-medium"
          style={{
            color,
            background: `color-mix(in srgb, ${color} 14%, transparent)`,
          }}
        >
          <span
            aria-hidden
            className="h-2 w-2 shrink-0 rounded-full"
            style={{ background: color }}
          />
          <span className="truncate">{folder}</span>
        </span>
        <span className="section-label">Selected</span>
      </div>

      <h2 className="mt-4 text-[20px] font-semibold leading-tight tracking-[-0.01em] text-primary [overflow-wrap:anywhere]">
        {title}
      </h2>
      <p className="mono mt-1.5 text-[12px] text-tertiary">
        {linkedNotes} linked {linkedNotes === 1 ? "note" : "notes"}
      </p>

      <p className="mt-3 line-clamp-5 text-[14px] leading-[1.6] text-secondary">
        {!current
          ? "Loading preview…"
          : current.error
            ? `Preview unavailable: ${current.error}`
            : current.text || "This note is empty."}
      </p>

      <div className="mt-4 flex flex-col gap-2">
        <button
          type="button"
          onClick={onOpen}
          className="flex h-11 items-center justify-center gap-2 rounded-button bg-accent text-[14px] font-semibold text-accent-ink transition-colors hover:bg-accent-hover"
        >
          Open note
          <ArrowUpRight aria-hidden className="h-4 w-4" strokeWidth={2} />
        </button>
        <button
          type="button"
          onClick={onAsk}
          className="flex h-11 items-center justify-center gap-2 rounded-button border border-button bg-active text-[14px] font-medium text-primary transition-colors hover:border-strong"
        >
          <Sparkles aria-hidden className="h-4 w-4 text-accent" strokeWidth={1.75} />
          Ask about it
        </button>
      </div>

      <hr className="my-5 border-0 border-t border-divider" />

      <div className="flex items-center justify-between">
        <h3 className="section-label">Connected notes</h3>
        <span className="mono text-[11px] text-tertiary">{neighbors.length}</span>
      </div>
      {neighbors.length === 0 ? (
        <p className="mt-2 text-[13px] text-tertiary">No links to other notes yet.</p>
      ) : (
        <ul className="-mx-2 mt-2 flex min-h-[96px] flex-1 flex-col gap-0.5 overflow-y-auto px-2 pb-1 max-[800px]:max-h-[360px]">
          {neighbors.map((n) => (
            <li key={n.id}>
              <button
                type="button"
                onClick={() => onSelect(n.id)}
                className="flex h-12 w-full items-center gap-2.5 rounded-item px-2.5 text-left transition-colors hover:bg-hover"
              >
                <span
                  aria-hidden
                  className="h-[9px] w-[9px] shrink-0 rounded-full"
                  style={
                    n.chat
                      ? { border: `1.5px solid ${n.color}` }
                      : { background: n.color }
                  }
                />
                <span className="min-w-0 flex-1 truncate text-[14px] text-primary">
                  {n.title}
                </span>
                <span className="max-w-[90px] shrink-0 truncate text-[12px] text-tertiary">
                  {n.folder}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
