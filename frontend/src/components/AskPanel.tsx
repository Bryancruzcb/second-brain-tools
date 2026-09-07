"use client";

import { useCallback, useState } from "react";
import { composePrompts, notes } from "@/data/mock";
import { GlowOutline } from "./GlowOutline";

type Props = {
  contextNoteId: string | null;
  onClearContext: () => void;
  sectionGlow?: boolean;
};

type AskAnswer = {
  query: string;
  body: string;
  sourceTitle: string | null;
};

function mockReply(query: string, contextNoteId: string | null): AskAnswer {
  const contextNote = contextNoteId
    ? notes.find((n) => n.id === contextNoteId)
    : null;

  const q = query.trim().toLowerCase();

  // Prefer context note when present
  if (contextNote) {
    const excerpt =
      contextNote.excerpt ||
      contextNote.body.split("\n").find((l) => l.trim()) ||
      contextNote.title;
    return {
      query,
      sourceTitle: contextNote.title,
      body: `From “${contextNote.title}”: ${excerpt} — ${contextNote.body
        .split("\n")
        .map((l) => l.trim())
        .filter(Boolean)
        .slice(0, 2)
        .join(" ")}`,
    };
  }

  // Grounded-looking templates from mock vault
  if (q.includes("broken") || q.includes("fix") || q.includes("health")) {
    return {
      query,
      sourceTitle: "Vault health taxonomy",
      body: "Two broken links (Inbox scrap → missing spaced-repetition note; Local Qwen prompts case mismatch), two orphans, two tagless notes. Start with retargeting the inbox scrap.",
    };
  }

  if (q.includes("capture") || q.includes("continuous")) {
    const n = notes.find((x) => x.id === "n1")!;
    return {
      query,
      sourceTitle: n.title,
      body: `${n.excerpt} Principles: capture in the moment, link while fresh, review weekly.`,
    };
  }

  if (q.includes("related") || q.includes("notes related")) {
    return {
      query,
      sourceTitle: "Vault health taxonomy",
      body: "Related: Vault health taxonomy, Continuous capture loops, Meeting: Atlas redesign sync. Taxonomy covers broken · orphan · tagless.",
    };
  }

  // Fallback: first recent-ish note that matches words, else n1
  const hit =
    notes.find((n) =>
      q.split(/\s+/).some((w) => w.length > 3 && n.title.toLowerCase().includes(w)),
    ) ?? notes[0];

  return {
    query,
    sourceTitle: hit.title,
    body: `${hit.excerpt} ${hit.body
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
      .slice(0, 2)
      .join(" ")}`,
  };
}

export function AskPanel({
  contextNoteId,
  onClearContext,
  sectionGlow,
}: Props) {
  const [query, setQuery] = useState("");
  const [answer, setAnswer] = useState<AskAnswer | null>(null);
  const contextNote = contextNoteId
    ? notes.find((n) => n.id === contextNoteId)
    : null;

  const runAsk = useCallback(() => {
    const trimmed = query.trim();
    if (!trimmed) return;
    setAnswer(mockReply(trimmed, contextNoteId));
  }, [query, contextNoteId]);

  return (
    <GlowOutline
      id="ask"
      glow={sectionGlow}
      radius={18}
      className="h-full"
    >
      <div className="card-elevated flex h-full min-h-[200px] flex-col overflow-hidden">
        <div className="border-b border-hairline px-5 py-4">
          <h3 className="text-[16px] font-medium tracking-[-0.02em]">Ask</h3>
        </div>

        <div className="flex flex-1 flex-col gap-4 p-5">
          <div className="compose-bar">
            {contextNote && (
              <span className="context-chip shrink-0">
                <span className="max-w-[140px] truncate">{contextNote.title}</span>
                <button
                  type="button"
                  aria-label="Remove context"
                  onClick={onClearContext}
                >
                  ×
                </button>
              </span>
            )}
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  runAsk();
                }
              }}
              placeholder="Ask…"
              aria-label="Ask"
            />
            <button
              type="button"
              className="btn-primary h-9 shrink-0 px-3.5 text-[13px]"
              disabled={!query.trim()}
              style={
                !query.trim()
                  ? { opacity: 0.45, cursor: "not-allowed" }
                  : undefined
              }
              onClick={runAsk}
            >
              Ask
            </button>
          </div>

          {answer && (
            <div className="ask-answer" role="status" aria-live="polite">
              <p>{answer.body}</p>
              {answer.sourceTitle && (
                <div className="ask-sources">
                  <span className="ask-sources-label">Source</span>
                  <span className="tag-chip">{answer.sourceTitle}</span>
                </div>
              )}
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            {composePrompts.map((p) => (
              <button
                key={p}
                type="button"
                className="rounded-xl border border-hairline bg-[#fafafa] px-3.5 py-2.5 text-left text-[13px] tracking-[-0.01em] text-ink/85 transition hover:border-[color-mix(in_srgb,var(--accent)_40%,var(--hairline))] hover:bg-white focus-ring"
                onClick={() => setQuery(p)}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
      </div>
    </GlowOutline>
  );
}
