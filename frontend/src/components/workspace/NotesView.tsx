"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  CircleAlert,
  CircleCheck,
  FileText,
  List,
  Loader,
  Maximize2,
  Minimize2,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
} from "lucide-react";
import { ApiError, fetchGraph, fetchRecent, folderCluster, recentToNote } from "@/lib/api";
import { relativeDay } from "@/lib/format";
import { cleanSnippet } from "@/lib/noteText";
import { isMapOnly, toggleMapOnly } from "@/lib/panes";
import { indexStatus } from "@/lib/status";
import { buildGlobe, type Globe } from "@/lib/vaultGlobe";
import type { Note } from "@/types";
import { useWorkspace } from "./context";
import { AskDock } from "./AskDock";
import { NoteInspector } from "./NoteInspector";
import { usePanes } from "./usePanes";
import { GlobeLegend, VaultGlobe } from "./VaultGlobe";

type Recent =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; notes: Note[] };

type Vault = { status: "loading" | "error" } | { status: "ready"; globe: Globe };

const NARROW = "(max-width: 900px)";

/** Scroll an element into view on the one-column layout, where it may be off screen. */
function revealOnNarrow(el: HTMLElement | null) {
  if (!el || !window.matchMedia(NARROW).matches) return;
  const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
}

/**
 * The main screen: Recent (a plain list), the 3D map of the whole vault with
 * the Ask dock under it, and the reading pane. The newest note is open until
 * another is picked. Recent and the reading pane fold to slim rails; with both
 * folded ("Map only") the map gets the width and most of the height.
 */
export function NotesView() {
  const { selectedNoteId, selectNote, ready } = useWorkspace();
  const [recent, setRecent] = useState<Recent>({ status: "loading" });
  const [vault, setVault] = useState<Vault>({ status: "loading" });
  const [sourceIds, setSourceIds] = useState<ReadonlySet<string>>(new Set());
  const [nowMs] = useState(() => Date.now());
  const [panes, setPanes] = usePanes();
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
        if (!cancelled) setVault({ status: "ready", globe: buildGlobe(g.nodes || [], g.edges || []) });
      })
      .catch(() => {
        if (!cancelled) setVault({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const notes = useMemo(() => (recent.status === "ready" ? recent.notes : []), [recent]);
  const globe = vault.status === "ready" ? vault.globe : null;
  /** Every note the map can show, including a chat's project copies (shown as the chat). */
  const mapIds = useMemo(
    () => new Set<string>(globe ? [...globe.nodes.map((n) => n.id), ...globe.aliases.keys()] : []),
    [globe],
  );

  const openId = selectedNoteId ?? notes[0]?.id ?? null;
  const openNote = notes.find((n) => n.id === openId);
  const sourceOnMap = [...sourceIds].some((id) => mapIds.has(id));

  const pick = (id: string, reveal: "reader" | "map" = "reader") => {
    selectNote(id, { repairIssueId: null });
    // Picking a note opens it, so a folded reading pane comes back; "Show on map" leaves it folded.
    if (reveal === "reader" && !panes.reader) setPanes({ ...panes, reader: true });
    revealOnNarrow(reveal === "reader" ? readerRef.current : skyRef.current);
  };
  const mapOnly = isMapOnly(panes);
  const layoutClass = [
    "notes-layout",
    panes.recent ? null : "recent-closed",
    panes.reader ? null : "reader-closed",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={layoutClass}>
      <RecentList
        recent={recent}
        openId={openId}
        nowMs={nowMs}
        onPick={(id) => pick(id)}
        open={panes.recent}
        onToggle={() => setPanes({ ...panes, recent: !panes.recent })}
      />
      <div className="center">
        <Lead recent={recent} notes={notes} ready={ready} />
        <div ref={skyRef} style={{ scrollMarginTop: 72 }}>
          <VaultGlobe
            className="sky"
            label="3D map of your vault"
            globe={globe}
            state={vault.status}
            selectedId={openId}
            turnToId={selectedNoteId}
            sourceIds={sourceIds}
            onPick={(id) => pick(id)}
            head={
              globe && (
                <>
                  <p className="constellation-count mono">
                    <b className="num">{globe.counts.chats}</b> AI chats · <b className="num">{globe.counts.notes}</b> notes ·{" "}
                    <b className="num">{globe.counts.folders}</b> folders
                  </p>
                  <a className="to-list" href="#recent">
                    <List className="icon" aria-hidden strokeWidth={2} />
                    List view
                  </a>
                  <button type="button" className="btn map-only" onClick={() => setPanes(toggleMapOnly(panes))}>
                    {mapOnly ? (
                      <Minimize2 className="icon" aria-hidden strokeWidth={2} />
                    ) : (
                      <Maximize2 className="icon" aria-hidden strokeWidth={2} />
                    )}
                    {mapOnly ? "Show panels" : "Map only"}
                  </button>
                </>
              )
            }
          />
        </div>
        {globe && <GlobeLegend showSource={sourceOnMap} />}
        <AskDock
          nowMs={nowMs}
          mapIds={mapIds}
          onSources={setSourceIds}
          onShowSource={(id, onMap) => pick(id, onMap ? "map" : "reader")}
        />
      </div>
      <section
        className={`reader${panes.reader ? "" : " is-closed"}`}
        ref={readerRef}
        aria-label="Reading pane"
        style={{ scrollMarginTop: 56 }}
      >
        <PaneRail side="right" label="Reading" onOpen={() => setPanes({ ...panes, reader: true })} />
        {recent.status === "loading" && !selectedNoteId ? (
          <ReaderSkeleton />
        ) : (
          <NoteInspector
            noteId={openId}
            updatedAt={openNote?.updatedAt}
            headAction={
              <button
                type="button"
                className="btn btn-quiet btn-icon pane-fold"
                style={{ marginLeft: "auto" }}
                onClick={() => setPanes({ ...panes, reader: false })}
                aria-label="Hide the reading pane"
                title="Hide the reading pane"
              >
                <PanelRightClose className="icon" aria-hidden strokeWidth={2} />
              </button>
            }
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

/** What a folded pane leaves behind: a slim full-height button that opens it again. */
function PaneRail({ side, label, onOpen }: { side: "left" | "right"; label: string; onOpen: () => void }) {
  const Icon = side === "left" ? PanelLeftOpen : PanelRightOpen;
  const name = side === "left" ? `Show the ${label} list` : "Show the reading pane";
  return (
    <button type="button" className="pane-rail" onClick={onOpen} aria-label={name} title={name}>
      <span className="pane-rail-inner">
        <Icon className="icon" aria-hidden strokeWidth={2} />
        <span className="pane-rail-label">{label}</span>
      </span>
    </button>
  );
}

function RecentList({
  recent,
  openId,
  nowMs,
  onPick,
  open,
  onToggle,
}: {
  recent: Recent;
  openId: string | null;
  nowMs: number;
  onPick: (id: string) => void;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <section
      className={`recent${open ? "" : " is-closed"}`}
      id="recent"
      aria-labelledby="recent-h"
      style={{ scrollMarginTop: 56 }}
    >
      <PaneRail side="left" label="Recent" onOpen={onToggle} />
      <div className="pane-head">
        <h2 id="recent-h">Recent</h2>
        <button
          type="button"
          className="btn btn-quiet btn-icon pane-fold"
          onClick={onToggle}
          aria-label="Hide the Recent list"
          title="Hide the Recent list"
        >
          <PanelLeftClose className="icon" aria-hidden strokeWidth={2} />
        </button>
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
