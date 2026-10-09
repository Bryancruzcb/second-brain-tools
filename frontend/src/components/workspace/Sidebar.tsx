"use client";

import {
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  Activity,
  FileText,
  Map as MapIcon,
  MessageSquare,
  Plus,
  Search,
} from "lucide-react";
import {
  ApiError,
  createNote,
  fetchAskHistory,
  type AskHistoryEntry,
} from "@/lib/api";
import { PRODUCT_NAME, VIEW_META, VIEWS, type ViewId } from "@/lib/workspace";
import { useWorkspace } from "./context";

const ICONS: Record<ViewId, typeof FileText> = {
  notes: FileText,
  map: MapIcon,
  ask: MessageSquare,
  health: Activity,
};

const RECENT_QUESTION_LIMIT = 8;

function AtlasLogo() {
  return (
    <span
      aria-hidden
      className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[9px] bg-accent"
    >
      {/* three dots joined by lines */}
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
        <path
          d="M4 13.2 9 4.6l5 7.6"
          stroke="var(--accent-ink)"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="4" cy="13.2" r="2.3" fill="var(--accent-ink)" />
        <circle cx="9" cy="4.6" r="2.3" fill="var(--accent-ink)" />
        <circle cx="14" cy="12.2" r="2.3" fill="var(--accent-ink)" />
      </svg>
    </span>
  );
}

function NavRow({ id }: { id: ViewId }) {
  const { view, setView, openIssueCount } = useWorkspace();
  const Icon = ICONS[id];
  const meta = VIEW_META[id];
  const active = view === id;
  const badge = id === "health" && openIssueCount ? openIssueCount : null;
  return (
    <button
      type="button"
      aria-current={active ? "page" : undefined}
      aria-keyshortcuts={`Meta+${meta.shortcut} Control+${meta.shortcut}`}
      onClick={() => setView(id)}
      className={`flex h-11 w-full items-center gap-3 rounded-control px-3 text-left text-[14px] font-medium transition-colors ${
        active
          ? "bg-active text-primary"
          : "text-secondary hover:bg-nav-hover hover:text-primary"
      }`}
    >
      <Icon
        aria-hidden
        className={`h-[18px] w-[18px] shrink-0 ${active ? "text-accent" : ""}`}
        strokeWidth={1.75}
      />
      <span className="min-w-0 flex-1 truncate">{meta.label}</span>
      {badge != null && (
        <span className="mono inline-flex h-5 min-w-5 items-center justify-center rounded-chip bg-warning-tint px-1.5 text-[11px] font-medium text-warning">
          {badge}
          <span className="sr-only"> open items</span>
        </span>
      )}
      <span aria-hidden className="mono text-[11px] text-tertiary">
        ⌘{meta.shortcut}
      </span>
    </button>
  );
}

function FolderList() {
  const { folders, vaultStatus, folderFilter, setFolderFilter, view, setView } =
    useWorkspace();

  let body: ReactNode;
  if (vaultStatus === "loading") {
    body = <p className="px-3 text-[13px] text-tertiary">Loading folders…</p>;
  } else if (vaultStatus === "error") {
    body = <p className="px-3 text-[13px] text-tertiary">Folders unavailable.</p>;
  } else if (folders.length === 0) {
    body = <p className="px-3 text-[13px] text-tertiary">No folders indexed yet.</p>;
  } else {
    body = (
      <ul className="sidebar-list flex flex-col gap-0.5">
        {folders.map((f) => {
          const active = folderFilter === f.name;
          return (
            <li key={f.name}>
              <button
                type="button"
                aria-pressed={active}
                title={`${f.name} · ${f.count} notes · show on Map`}
                onClick={() => {
                  setFolderFilter(active ? null : f.name);
                  // TODO(notes-step): filter the Notes list by folder too; for
                  // now folders filter the Map, so jump there.
                  if (view !== "map") setView("map");
                }}
                className={`flex h-[38px] w-full items-center gap-2.5 rounded-control px-3 text-left text-[14px] transition-colors ${
                  active
                    ? "bg-active text-primary"
                    : "text-secondary hover:bg-nav-hover hover:text-primary"
                }`}
              >
                <span
                  aria-hidden
                  className="h-[9px] w-[9px] shrink-0 rounded-full"
                  style={{ background: f.color }}
                />
                <span className="min-w-0 flex-1 truncate">{f.name}</span>
              </button>
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <section aria-labelledby="sidebar-folders" className="flex min-h-0 flex-col gap-2">
      <h2 id="sidebar-folders" className="section-label px-3">
        Folders
      </h2>
      {body}
    </section>
  );
}

function RecentQuestions() {
  const { askHistoryVersion, pickAskEntry, askPick } = useWorkspace();
  const [entries, setEntries] = useState<AskHistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchAskHistory(RECENT_QUESTION_LIMIT)
      .then((res) => {
        if (cancelled) return;
        setEntries(res.entries || []);
        setError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setEntries([]);
        setError(e instanceof ApiError ? e.message : "Could not load questions.");
      });
    return () => {
      cancelled = true;
    };
  }, [askHistoryVersion]);

  let body: ReactNode;
  if (entries === null) {
    body = <p className="px-3 text-[13px] text-tertiary">Loading…</p>;
  } else if (error) {
    body = <p className="px-3 text-[13px] text-tertiary">Questions unavailable.</p>;
  } else if (entries.length === 0) {
    body = <p className="px-3 text-[13px] text-tertiary">No questions yet.</p>;
  } else {
    body = (
      <ul className="sidebar-list flex flex-col gap-0.5">
        {entries.map((entry) => {
          const active = askPick?.entry.id === entry.id;
          return (
            <li key={entry.id}>
              <button
                type="button"
                aria-current={active ? "true" : undefined}
                title={entry.question}
                onClick={() => pickAskEntry(entry)}
                className={`flex h-[38px] w-full items-center gap-2.5 rounded-control px-3 text-left text-[14px] transition-colors ${
                  active
                    ? "bg-active text-primary"
                    : "text-secondary hover:bg-nav-hover hover:text-primary"
                }`}
              >
                <span className="min-w-0 flex-1 truncate">{entry.question}</span>
              </button>
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <section aria-labelledby="sidebar-recent" className="flex min-h-0 flex-col gap-2">
      <h2 id="sidebar-recent" className="section-label px-3">
        Recent questions
      </h2>
      {body}
    </section>
  );
}

function NewNote() {
  const { refreshVault } = useWorkspace();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(
    null,
  );
  const inputRef = useRef<HTMLInputElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const inputId = useId();
  const statusId = useId();

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const close = () => {
    setOpen(false);
    setTitle("");
    queueMicrotask(() => triggerRef.current?.focus());
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const trimmed = title.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await createNote(trimmed);
      // TODO(notes-step): open the new note in the reader. The backend only
      // serves notes that are in its index, so a brand-new file 404s until
      // the next scan/re-index picks it up.
      setMessage({
        tone: "ok",
        text: `Created “${res.title}”. It shows up after the next re-index.`,
      });
      refreshVault();
      close();
    } catch (err) {
      setMessage({
        tone: "error",
        text: err instanceof ApiError ? err.message : "Could not create the note.",
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      {open ? (
        <form
          onSubmit={(e) => void onSubmit(e)}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              close();
            }
          }}
          className="flex flex-col gap-2 rounded-item border border-button bg-surface p-2"
          aria-describedby={message ? statusId : undefined}
        >
          <label htmlFor={inputId} className="section-label px-1 pt-1">
            New note title
          </label>
          <input
            id={inputId}
            ref={inputRef}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Note title"
            autoComplete="off"
            disabled={busy}
            className="h-11 w-full rounded-control border border-control bg-page px-3 text-[14px] text-primary placeholder:text-tertiary"
          />
          <div className="flex gap-2">
            <button
              type="button"
              onClick={close}
              className="h-11 flex-1 rounded-button border border-button bg-active text-[14px] font-medium text-secondary hover:border-strong hover:text-primary"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!title.trim() || busy}
              className="h-11 flex-1 rounded-button bg-accent text-[14px] font-semibold text-accent-ink hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busy ? "Creating…" : "Create"}
            </button>
          </div>
        </form>
      ) : (
        <button
          ref={triggerRef}
          type="button"
          onClick={() => {
            setMessage(null);
            setOpen(true);
          }}
          className="flex h-11 w-full items-center justify-center gap-2 rounded-button bg-accent text-[14px] font-semibold text-accent-ink transition-colors hover:bg-accent-hover"
        >
          <Plus aria-hidden className="h-[18px] w-[18px]" strokeWidth={2} />
          New note
        </button>
      )}
      <p
        id={statusId}
        role="status"
        className={`px-1 text-[12px] ${
          message?.tone === "error" ? "text-danger" : "text-tertiary"
        } ${message ? "" : "sr-only"}`}
      >
        {message?.text}
      </p>
    </div>
  );
}

function StatusCard() {
  const { ready, noteCount, chatCount } = useWorkspace();

  let label: string;
  let dot: string;
  let ring: string;
  if (!ready) {
    label = "Checking index…";
    dot = "var(--text-tertiary)";
    ring = "rgba(134, 140, 148, 0.18)";
  } else if (!ready.reachable) {
    label = "Backend offline";
    dot = "var(--danger)";
    ring = "rgba(240, 141, 178, 0.18)";
  } else if (ready.ready && ready.indexPopulated !== false) {
    label = "Index ready";
    dot = "var(--success)";
    ring = "var(--success-ring)";
  } else if (ready.indexPopulated === false) {
    label = "Index empty";
    dot = "var(--warning)";
    ring = "var(--warning-tint)";
  } else {
    label = "Loading search…";
    dot = "var(--warning)";
    ring = "var(--warning-tint)";
  }

  const counts =
    noteCount != null && chatCount != null
      ? `${noteCount.toLocaleString("en-US")} notes · ${chatCount.toLocaleString(
          "en-US",
        )} chats`
      : "Counts unavailable";

  const detail = ready?.components
    ? Object.entries(ready.components)
        .map(([k, v]) => `${k}: ${v ? "on" : "off"}`)
        .join("\n")
    : undefined;

  return (
    <div
      role="status"
      title={detail}
      className="flex items-center gap-3 rounded-item border border-divider bg-status px-3.5 py-3"
    >
      <span
        aria-hidden
        className="h-2 w-2 shrink-0 rounded-full"
        style={{ background: dot, boxShadow: `0 0 0 3px ${ring}` }}
      />
      <span className="flex min-w-0 flex-col">
        <span className="text-[13px] font-medium text-primary">{label}</span>
        <span className="mono truncate text-[11px] text-tertiary">{counts}</span>
      </span>
    </div>
  );
}

export function Sidebar() {
  const { view, setCommandOpen } = useWorkspace();

  return (
    <aside className="sidebar" aria-label="Sidebar">
      <div className="flex items-center gap-2.5">
        <AtlasLogo />
        <div className="flex min-w-0 flex-col">
          <span className="text-[15px] font-semibold leading-5 text-primary">
            {PRODUCT_NAME}
          </span>
          <span className="text-[12px] leading-4 text-tertiary">Personal vault</span>
        </div>
      </div>

      <button
        type="button"
        onClick={() => setCommandOpen(true)}
        aria-keyshortcuts="Meta+K Control+K"
        aria-haspopup="dialog"
        className="flex h-11 w-full items-center gap-2 rounded-control border border-control bg-surface px-3 text-left text-[13px] text-tertiary transition-colors hover:border-strong hover:text-secondary"
      >
        <Search aria-hidden className="h-4 w-4 shrink-0" strokeWidth={1.75} />
        <span className="min-w-0 flex-1 truncate">Search or jump to…</span>
        <kbd className="kbd">⌘K</kbd>
      </button>

      <nav aria-label="Views" className="sidebar-nav flex flex-col gap-0.5">
        {VIEWS.map((id) => (
          <NavRow key={id} id={id} />
        ))}
      </nav>

      {view === "ask" ? <RecentQuestions /> : <FolderList />}

      <div className="sidebar-spacer" aria-hidden />

      <div className="sidebar-footer flex flex-col gap-3">
        <NewNote />
        <StatusCard />
      </div>
    </aside>
  );
}

