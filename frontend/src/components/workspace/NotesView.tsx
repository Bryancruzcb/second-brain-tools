"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CircleAlert, CircleCheck, FileText, Loader } from "lucide-react";
import {
  ApiError,
  fetchGraph,
  fetchRecent,
  folderCluster,
  recentToNote,
  type BackendGraphEdge,
} from "@/lib/api";
import { relativeDay } from "@/lib/format";
import { cleanSnippet } from "@/lib/noteText";
import { layoutStarChart, type ChartNote } from "@/lib/starChart";
import { indexStatus } from "@/lib/status";
import type { Note } from "@/types";
import { useWorkspace } from "./context";
import { AskDock } from "./AskDock";
import { NoteInspector } from "./NoteInspector";
import { ChartLegend, StarChart, type ChartState } from "./StarChart";

type Recent =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; notes: Note[] };

type Links = { status: "loading" | "error" } | { status: "ready"; edges: BackendGraphEdge[] };

const NARROW = "(max-width: 900px)";

/** Scroll an element into view on the one-column layout, where it may be off screen. */
function revealOnNarrow(el: HTMLElement | null) {
  if (!el || !window.matchMedia(NARROW).matches) return;
  const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
}

/**
 * The main screen: Recent (a plain list), the star chart of those notes with
 * the Ask dock under it, and the reading pane. The newest note is open until
 * another is picked.
 */
export function NotesView() {
  const { selectedNoteId, selectNote, ready } = useWorkspace();
  const [recent, setRecent] = useState<Recent>({ status: "loading" });
  const [links, setLinks] = useState<Links>({ status: "loading" });
  const [sourceIds, setSourceIds] = useState<ReadonlySet<string>>(new Set());
  const [nowMs] = useState(() => Date.now());
  const readerRef = useRef<HTMLElement>(null);
  const skyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    fetchRecent()
      .then((res) => {
        if (!cancelled) setRecent({ status: "ready", notes: (res.notes || []).map(recentToNote) });
      })
      .catch((e) => {
        if (!cancelled)
          setRecent({
            status: "error",
            message: e instanceof ApiError ? e.message : "Could not load recent notes.",
          });
      });
    fetchGraph()
      .then((g) => {
        if (!cancelled) setLinks({ status: "ready", edges: g.edges || [] });
      })
      .catch(() => {
        if (!cancelled) setLinks({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const notes = useMemo(() => (recent.status === "ready" ? recent.notes : []), [recent]);
  const chartNotes: ChartNote[] = useMemo(
    () =>
      notes.map((n) => ({
        id: n.id,
        title: n.title,
        editedMs: Date.parse(n.updatedAt),
      })),
    [notes],
  );
  const chart = useMemo(
    () => layoutStarChart(chartNotes, links.status === "ready" ? links.edges : [], nowMs),
    [chartNotes, links, nowMs],
  );
  const editedIso = useMemo(() => Object.fromEntries(notes.map((n) => [n.id, n.updatedAt])), [notes]);

  const openId = selectedNoteId ?? notes[0]?.id ?? null;
  const openNote = notes.find((n) => n.id === openId);
  const chartState: ChartState =
    recent.status === "ready" ? (notes.length ? "ready" : "empty") : recent.status;
  const sourceOnChart = notes.some((n) => sourceIds.has(n.id));

  const pick = (id: string, reveal: "reader" | "chart" = "reader") => {
    selectNote(id, { repairIssueId: null });
    revealOnNarrow(reveal === "reader" ? readerRef.current : skyRef.current);
  };

  return (
    <div className="notes-layout">
      <RecentList
        recent={recent}
        openId={openId}
        nowMs={nowMs}
        onPick={(id) => pick(id)}
      />
      <div className="center">
        <Lead recent={recent} notes={notes} ready={ready} />
        <div ref={skyRef} style={{ scrollMarginTop: 72 }}>
          <StarChart
            state={chartState}
            chart={chart}
            editedIso={editedIso}
            selectedId={openId}
            sourceIds={sourceIds}
            onSelect={(id) => pick(id)}
            nowMs={nowMs}
          />
        </div>
        {chartState === "ready" && (
          <ChartLegend
            chart={chart}
            linksKnown={links.status === "ready"}
            sourceOnChart={sourceOnChart}
          />
        )}
        <AskDock
          nowMs={nowMs}
          chartIds={new Set(notes.map((n) => n.id))}
          onSources={setSourceIds}
          onShowSource={(id, onChart) => pick(id, onChart ? "chart" : "reader")}
        />
      </div>
      <section className="reader" ref={readerRef} aria-label="Reading pane" style={{ scrollMarginTop: 56 }}>
        {recent.status === "loading" && !selectedNoteId ? (
          <ReaderSkeleton />
        ) : (
          <NoteInspector
            noteId={openId}
            updatedAt={openNote?.updatedAt}
          />
        )}
      </section>
    </div>
  );
}

function Lead({
  recent,
  notes,
  ready,
}: {
  recent: Recent;
  notes: Note[];
  ready: ReturnType<typeof useWorkspace>["ready"];
}) {
  if (recent.status === "loading") {
    return (
      <div aria-busy="true" aria-label="Loading">
        <span className="sk" style={{ width: "24%", height: 26 }} />
      </div>
    );
  }
  if (recent.status === "error") {
    return (
      <h1 className="lead">
        <CircleAlert className="bad" aria-hidden strokeWidth={2} />
        <span>
          Notes could not load.{" "}
          <span className="soft">
            {/[.?!]$/.test(recent.message) ? recent.message : `${recent.message}.`} Start the backend,
            then reload.
          </span>
        </span>
      </h1>
    );
  }
  const status = indexStatus(ready);
  const Icon = status.tone === "ok" ? CircleCheck : status.tone === "bad" ? CircleAlert : Loader;
  return (
    <h1 className="lead">
      <span title={status.detail} style={{ display: "flex" }}>
        <Icon className={status.tone === "ok" ? "ok" : status.tone === "bad" ? "bad" : "wait"} aria-hidden strokeWidth={2} />
      </span>
      <span>
        {status.text}.
        {notes.length === 0 && <span className="soft"> No notes indexed yet.</span>}
      </span>
    </h1>
  );
}

function RecentList({
  recent,
  openId,
  nowMs,
  onPick,
}: {
  recent: Recent;
  openId: string | null;
  nowMs: number;
  onPick: (id: string) => void;
}) {
  return (
    <section className="recent" id="recent" aria-labelledby="recent-h" style={{ scrollMarginTop: 56 }}>
      <div className="pane-head">
        <h2 id="recent-h">Recent</h2>
      </div>
      {recent.status === "loading" ? (
        <ul className="rows" aria-busy="true" aria-label="Loading recent notes">
          {Array.from({ length: 6 }, (_, i) => (
            <li key={i} className="row" style={{ display: "block" }}>
              <span className="sk" style={{ width: "55%" }} />
              <span className="sk" style={{ width: "90%", height: 12, marginTop: 8 }} />
            </li>
          ))}
        </ul>
      ) : recent.status === "error" ? (
        <div className="pane-msg bad">
          <CircleAlert aria-hidden strokeWidth={2} />
          <strong>Recent notes could not load.</strong>
          They come back when the backend is running.
        </div>
      ) : recent.notes.length === 0 ? (
        <div className="pane-msg">
          <FileText aria-hidden strokeWidth={2} />
          <strong>No recent notes yet.</strong>
          Start the backend or wait for the index to scan your vault.
        </div>
      ) : (
        <ul className="rows">
          {recent.notes.map((n) => (
            <li key={n.id}>
              <button
                type="button"
                className="row"
                aria-pressed={n.id === openId}
                title={`${n.title} (${folderCluster(n.id)})`}
                onClick={() => onPick(n.id)}
              >
                <span className="dotcell" aria-hidden>
                  <span className="dot" style={{ width: 7, height: 7 }} />
                </span>
                <span className="t">{n.title}</span>
                <span className="d mono num">{relativeDay(n.updatedAt, nowMs)}</span>
                <span className="s">{cleanSnippet(n.body, n.title)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ReaderSkeleton() {
  return (
    <div className="inspector" aria-busy="true" aria-label="Loading the reading pane">
      <div className="inspector-head">
        <span className="sk" style={{ width: "70%", height: 30, marginTop: 4 }} />
        <span className="sk" style={{ width: "55%", height: 12, marginTop: 12 }} />
        <span className="sk" style={{ width: "100%", marginTop: 40 }} />
        <span className="sk" style={{ width: "92%", marginTop: 10 }} />
        <span className="sk" style={{ width: "60%", marginTop: 10 }} />
      </div>
    </div>
  );
}
