"use client";

import { useEffect, useId, useState } from "react";
import { CircleAlert, FileText, MessageSquareText, Pencil, TriangleAlert } from "lucide-react";
import { ApiError, fetchNote, folderCluster, saveNote } from "@/lib/api";
import { editedPhrase, relativeDay } from "@/lib/format";
import { noteBlocks } from "@/lib/noteText";
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
  /** the note to show; defaults to the workspace's selected note */
  noteId?: string | null;
  /** last edit time, when the caller knows it (the Recent list does) */
  updatedAt?: string;
  repairIssue?: HealthIssue | null;
  onClose?: () => void;
};

/** The reading pane: title once, file, folder and edit time, then the note. Edit and save stay here. */
export function NoteInspector({ noteId, updatedAt, repairIssue = null, onClose }: Props) {
  const { selectedNoteId, setAskContextId, setView } = useWorkspace();
  const id = noteId === undefined ? selectedNoteId : noteId;
  const [loadedId, setLoadedId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [draft, setDraft] = useState("");
  const [readOnly, setReadOnly] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [editFor, setEditFor] = useState<string | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const headingId = useId();

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      try {
        const n = await fetchNote(id);
        if (cancelled) return;
        setTitle(n.title);
        setBody(n.content);
        setDraft(n.content);
        setReadOnly(Boolean(n.read_only_fallback));
        setError(null);
        setSavedAt(null);
        setLoadFailed(false);
        setLoadedId(id);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof ApiError ? e.message : "Could not load note.");
        setTitle(id.split("/").pop()?.replace(/\.md$/i, "") || id);
        setBody("");
        setDraft("");
        setReadOnly(false);
        setLoadFailed(true);
        setLoadedId(id);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (!id) {
    return (
      <div className="inspector">
        <div className="inspector-head">
          <div className="pane-msg" style={{ margin: "16px 0" }}>
            <FileText aria-hidden strokeWidth={2} />
            <strong>Nothing open.</strong>
            Pick a note to read it here.
          </div>
        </div>
      </div>
    );
  }

  const loading = loadedId !== id;
  const editing = editFor === id;
  const dirty = editing && draft !== body;

  const onSave = async () => {
    if (readOnly) return;
    setSaving(true);
    setError(null);
    try {
      await saveNote(id, draft);
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
    <article className="inspector" aria-labelledby={headingId} aria-busy={loading || undefined}>
      <div className="inspector-head">
        {onClose && (
          <p className="kicker">
            <button type="button" className="btn btn-quiet" onClick={onClose} style={{ marginLeft: "auto" }}>
              Close
            </button>
          </p>
        )}
        {loading ? (
          <>
            <h2 id={headingId} className="sr-only">
              Loading note
            </h2>
            <span className="sk" style={{ width: "70%", height: 30, marginTop: 14 }} />
            <span className="sk" style={{ width: "55%", height: 12, marginTop: 12 }} />
          </>
        ) : (
          <>
            <h2 id={headingId}>{title || "Untitled"}</h2>
            <p className="meta mono">
              <span>{id}</span>
              <span>{folderCluster(id)}</span>
              {updatedAt && <span className="num">{editedPhrase(updatedAt)}</span>}
            </p>
          </>
        )}
        <div className="reader-actions">
          <button
            type="button"
            className="btn"
            onClick={() => {
              setAskContextId(id);
              setView("ask");
            }}
          >
            <MessageSquareText className="icon" aria-hidden strokeWidth={2} />
            Ask with this
          </button>
          {!readOnly && !editing && !loading && !loadFailed && (
            <button type="button" className="btn" onClick={() => setEditFor(id)}>
              <Pencil className="icon" aria-hidden strokeWidth={2} />
              Edit
            </button>
          )}
          {editing && (
            <>
              <button
                type="button"
                className="btn btn-quiet"
                onClick={() => {
                  setDraft(body);
                  setEditFor(null);
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={!dirty || saving}
                onClick={() => void onSave()}
              >
                {saving ? "Saving…" : "Save"}
              </button>
            </>
          )}
          {savedAt && (
            <span className="saved" role="status">
              Saved {relativeDay(savedAt).toLowerCase()}
            </span>
          )}
        </div>
      </div>

      <div className="inspector-body">
        <div className="note-body">
          {readOnly && (
            <p className="notice warn" role="status">
              <TriangleAlert className="icon" aria-hidden strokeWidth={2} />
              This file is a cloud placeholder. Showing the last indexed copy, read only.
            </p>
          )}
          {repairIssue && (
            <div className="repair-callout" style={{ marginBottom: 16 }}>
              <div className="flex flex-wrap items-center gap-2">
                <span className={`status-pill ${kindClass[repairIssue.kind]}`}>
                  {kindLabel[repairIssue.kind]}
                </span>
              </div>
              <p className="mt-1.5 text-[14px] leading-snug">{repairIssue.detail}</p>
              <p className="mt-1 text-[14px] text-accent">{repairIssue.action}</p>
            </div>
          )}
          {error && (
            <p className="notice bad" role="alert">
              <CircleAlert className="icon" aria-hidden strokeWidth={2} />
              {error}
            </p>
          )}
          {editing ? (
            <textarea
              className="note-editor focus-ring"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              aria-label="Note markdown"
            />
          ) : loading ? (
            <div aria-hidden>
              <span className="sk" style={{ width: "100%" }} />
              <span className="sk" style={{ width: "92%", marginTop: 10 }} />
              <span className="sk" style={{ width: "60%", marginTop: 10 }} />
            </div>
          ) : (
            <NoteText md={body} title={title} />
          )}
        </div>
      </div>
    </article>
  );
}

function NoteText({ md, title }: { md: string; title: string }) {
  const blocks = noteBlocks(md, title);
  if (!blocks.length) return <p style={{ color: "var(--muted)" }}>No content.</p>;
  return (
    <>
      {blocks.map((b, i) =>
        b.kind === "heading" ? (
          <h3 key={i}>{b.text}</h3>
        ) : b.kind === "code" ? (
          <pre key={i}>{b.text}</pre>
        ) : (
          <p key={i}>{b.text}</p>
        ),
      )}
    </>
  );
}
