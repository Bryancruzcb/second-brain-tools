"use client";

import { useEffect, useState } from "react";
import { ApiError, fetchNote, saveNote } from "@/lib/api";
import { relativeDay } from "@/lib/format";
import type { HealthIssue } from "@/types";
import { useWorkspace } from "./context";

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

type Props = {
  repairIssue?: HealthIssue | null;
  onClose?: () => void;
};

export function NoteInspector({ repairIssue = null, onClose }: Props) {
  const { selectedNoteId, setAskContextId, setView } = useWorkspace();
  const [loadedId, setLoadedId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [path, setPath] = useState("");
  const [body, setBody] = useState("");
  const [draft, setDraft] = useState("");
  const [readOnly, setReadOnly] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [editFor, setEditFor] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedNoteId) return;
    let cancelled = false;
    (async () => {
      try {
        const n = await fetchNote(selectedNoteId);
        if (cancelled) return;
        setTitle(n.title);
        setPath(selectedNoteId);
        setBody(n.content);
        setDraft(n.content);
        setReadOnly(Boolean(n.read_only_fallback));
        setError(null);
        setSavedAt(null);
        setLoadedId(selectedNoteId);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof ApiError ? e.message : "Could not load note.");
        setTitle(selectedNoteId.split("/").pop() || selectedNoteId);
        setPath(selectedNoteId);
        setBody("");
        setDraft("");
        setLoadedId(selectedNoteId);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedNoteId]);

  const loading = Boolean(selectedNoteId) && loadedId !== selectedNoteId;
  const editing = editFor === selectedNoteId;

  if (!selectedNoteId) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-[13px] text-muted">
        Select a note to read it here.
      </div>
    );
  }

  const dirty = editing && draft !== body;

  const onSave = async () => {
    if (readOnly || !selectedNoteId) return;
    setSaving(true);
    setError(null);
    try {
      await saveNote(selectedNoteId, draft);
      setBody(draft);
      setEditFor(null);
      setSavedAt(new Date().toISOString());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <article className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b border-hairline px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate text-[18px] font-medium tracking-[-0.02em]">
              {title || "Untitled"}
            </h2>
            <p className="mono mt-1 truncate text-[11px] text-muted">{path}</p>
          </div>
          {onClose && (
            <button type="button" className="btn btn-ghost btn-compact" onClick={onClose}>
              Close
            </button>
          )}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {savedAt ? (
            <span className="text-[11px] text-muted">Saved {relativeDay(savedAt)}</span>
          ) : null}
          {loading && <span className="text-[11px] text-muted">Loading…</span>}
          <button
            type="button"
            className="btn btn-ghost btn-compact"
            onClick={() => {
              setAskContextId(selectedNoteId);
              setView("ask");
            }}
          >
            Ask with this
          </button>
          {!readOnly && !editing && (
            <button
              type="button"
              className="btn btn-secondary btn-compact"
              onClick={() => setEditFor(selectedNoteId)}
            >
              Edit
            </button>
          )}
          {editing && (
            <>
              <button
                type="button"
                className="btn btn-ghost btn-compact"
                onClick={() => {
                  setDraft(body);
                  setEditFor(null);
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary btn-compact"
                disabled={!dirty || saving}
                onClick={() => void onSave()}
              >
                {saving ? "Saving…" : "Save"}
              </button>
            </>
          )}
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {readOnly && (
          <p className="mb-3 text-[12px] text-[var(--warning)]" role="status">
            This file is a cloud placeholder. Showing the last indexed copy — read only.
          </p>
        )}
        {repairIssue && (
          <div className="repair-callout mb-4">
            <div className="flex flex-wrap items-center gap-2">
              <span className={`status-pill ${kindClass[repairIssue.kind]}`}>
                {kindLabel[repairIssue.kind]}
              </span>
              <span className="text-[13px] font-medium">Repair</span>
            </div>
            <p className="mt-1.5 text-[13px] leading-snug">{repairIssue.detail}</p>
            <p className="mt-1 text-[12px] text-[var(--sky)]">{repairIssue.action}</p>
          </div>
        )}
        {error && (
          <p className="mb-3 text-[13px] text-[var(--danger)]" role="alert">
            {error}
          </p>
        )}
        {editing ? (
          <textarea
            className="focus-ring min-h-[24rem] w-full resize-y rounded-[7px] border border-hairline bg-elevated p-3 text-[14px] leading-relaxed"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            aria-label="Note markdown"
          />
        ) : (
          <div className="prose-note">{body || (loading ? "" : "No content.")}</div>
        )}
      </div>
    </article>
  );
}
