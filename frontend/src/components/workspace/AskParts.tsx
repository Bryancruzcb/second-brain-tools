"use client";

import { useEffect, useState, type ReactNode, type RefObject } from "react";
import { Lock, MessageSquareText, Search, X } from "lucide-react";
import { fetchNote, type AskScope } from "@/lib/api";
import { capitalize, SCOPES, type AskAnswer } from "@/lib/ask";
import { askedAgo } from "@/lib/format";
import { useWorkspace } from "./context";

/** The title of the note set as Ask context, falling back to its file name. */
function useContextTitle(id: string | null): string | null {
  const [fetched, setFetched] = useState<{ id: string; title: string } | null>(null);
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    fetchNote(id)
      .then((n) => {
        if (!cancelled && n.title) setFetched({ id, title: n.title });
      })
      .catch(() => {
        /* keep the file-name title */
      });
    return () => {
      cancelled = true;
    };
  }, [id]);
  if (!id) return null;
  if (fetched?.id === id) return fetched.title;
  return id.split("/").pop()?.replace(/\.md$/i, "") || id;
}

/**
 * The input row of Ask: optional context chip, the question, Find (dock only)
 * and Ask, then the scope choice and the privacy line.
 */
export function AskComposer({
  inputId,
  inputRef,
  query,
  onQuery,
  scope,
  onScope,
  loading,
  onAsk,
  onFind,
  first = false,
}: {
  inputId: string;
  inputRef?: RefObject<HTMLInputElement | null>;
  query: string;
  onQuery: (q: string) => void;
  scope: AskScope;
  onScope: (s: AskScope) => void;
  loading: boolean;
  onAsk: () => void;
  onFind?: () => void;
  first?: boolean;
}) {
  const { askContextId, setAskContextId } = useWorkspace();
  const contextTitle = useContextTitle(askContextId);
  const label = onFind ? "Ask a question or find a note" : "Ask the vault";

  return (
    <form
      className={`composer${first ? " first" : ""}`}
      onSubmit={(e) => {
        e.preventDefault();
        onAsk();
      }}
    >
      <div className="bar">
        <Search className="icon" aria-hidden strokeWidth={2} />
        {askContextId && contextTitle && (
          <span className="context-chip" title={`Asking with ${contextTitle}`}>
            <span>{contextTitle}</span>
            <button type="button" aria-label="Remove context" onClick={() => setAskContextId(null)}>
              <X className="icon" aria-hidden strokeWidth={2} />
            </button>
          </span>
        )}
        <label className="sr-only" htmlFor={inputId}>
          {label}
        </label>
        <input
          id={inputId}
          ref={inputRef}
          type="text"
          autoComplete="off"
          placeholder={label}
          aria-label={label}
          value={query}
          disabled={loading}
          onChange={(e) => onQuery(e.target.value)}
        />
        {onFind && (
          <button type="button" className="btn" disabled={!query.trim() || loading} onClick={onFind}>
            Find
          </button>
        )}
        <button type="submit" className="btn btn-primary" disabled={!query.trim() || loading}>
          {loading ? "Asking…" : "Ask"}
        </button>
      </div>
      <div className="scope">
        <div className="seg" role="group" aria-label="Look in">
          {SCOPES.map((s) => (
            <button
              key={s.id}
              type="button"
              title={s.hint}
              aria-pressed={scope === s.id}
              onClick={() => onScope(s.id)}
            >
              {s.label}
            </button>
          ))}
        </div>
        <span className="private">
          <Lock aria-hidden strokeWidth={2} />
          Answered by a local model. Nothing leaves this computer.
        </span>
      </div>
    </form>
  );
}

/**
 * An answer with numbered sources: [1] after the text links to source 1,
 * which shows the note title, its file name and the quoted text.
 */
export function AnswerBlock({
  answer,
  heading,
  idPrefix,
  writing,
  nowMs,
  sourceAction,
  actions,
}: {
  answer: AskAnswer;
  heading: string;
  idPrefix: string;
  writing: boolean;
  nowMs: number;
  /** a button per source, e.g. "Show on map" */
  sourceAction?: (source: AskAnswer["sources"][number]) => ReactNode;
  actions?: ReactNode;
}) {
  const meta = [
    heading,
    answer.askedAt !== null ? askedAgo(answer.askedAt, nowMs) : null,
    capitalize(answer.scope),
  ].filter(Boolean);
  const n = answer.sources.length;

  return (
    <div className="answer" aria-labelledby={`${idPrefix}-question`} aria-busy={writing || undefined}>
      <p className="dock-head mono">
        <MessageSquareText className="icon" aria-hidden strokeWidth={2} />
        {meta.join(" · ")}
      </p>
      <p className="question" id={`${idPrefix}-question`}>
        {capitalize(answer.question)}
      </p>
      <p className="answer-text" aria-live="polite">
        {answer.body || (writing ? "Writing…" : "")}
        {answer.sources.map((s, i) => (
          <a key={s.source || s.title} className="cite" href={`#${idPrefix}-src-${i + 1}`} aria-label={`Source ${i + 1}: ${s.title}`}>
            {i + 1}
          </a>
        ))}
      </p>
      {n > 0 && (
        <ol className="sources" aria-label={`From ${n} note${n === 1 ? "" : "s"}`}>
          {answer.sources.map((s, i) => (
            <li key={s.source || s.title} className="source" id={`${idPrefix}-src-${i + 1}`}>
              <span className="n mono">{i + 1}</span>
              <div className="what">
                <span className="t">{s.title}</span> <span className="f mono">{s.source}</span>
                {s.snippet && <blockquote>{s.snippet}</blockquote>}
              </div>
              {sourceAction?.(s)}
            </li>
          ))}
        </ol>
      )}
      {actions && <div className="answer-actions">{actions}</div>}
    </div>
  );
}
