"use client";

import { useEffect, useState } from "react";
import { productName } from "@/data/mock";
import { ApiError, fetchReady, fetchRecent, recentToNote } from "@/lib/api";
import { SECTIONS, type SectionId } from "@/lib/sections";
import type { Note } from "@/types";
import { BrandMark } from "./BrandMark";

type Props = {
  activeSection: SectionId | null;
  selectedNoteId: string | null;
  onNavigate: (section: SectionId) => void;
  onOpenNote: (id: string) => void;
};

type Backend = "checking" | "online" | "warming" | "offline";

const backendLabel: Record<Backend, string> = {
  checking: "Checking backend…",
  online: "Local backend online",
  warming: "Backend warming up…",
  offline: "Backend offline",
};

/** How often to re-check /api/ready until every component has loaded. */
const READY_POLL_MS = 8000;
const RECENT_LIMIT = 6;

export function Sidebar({
  activeSection,
  selectedNoteId,
  onNavigate,
  onOpenNote,
}: Props) {
  const [recent, setRecent] = useState<Note[]>([]);
  const [recentState, setRecentState] = useState<"loading" | "ok" | "down">(
    "loading",
  );
  const [backend, setBackend] = useState<Backend>("checking");

  useEffect(() => {
    let cancelled = false;
    fetchRecent()
      .then((res) => {
        if (cancelled) return;
        setRecent((res.notes || []).slice(0, RECENT_LIMIT).map(recentToNote));
        setRecentState("ok");
      })
      .catch(() => {
        if (!cancelled) setRecentState("down");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const check = async () => {
      let next: Backend;
      try {
        const res = await fetchReady();
        next = res.ready ? "online" : "warming";
      } catch (e) {
        // A reachable backend that 5xx's is still starting; status 0 means no socket.
        next = e instanceof ApiError && e.status !== 0 ? "warming" : "offline";
      }
      if (cancelled) return;
      setBackend(next);
      if (next !== "online") timer = setTimeout(check, READY_POLL_MS);
    };
    void check();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  return (
    <aside className="app-sidebar" aria-label="Workspace">
      <a
        href="#overview"
        className="sidebar-brand focus-ring"
        onClick={(e) => {
          e.preventDefault();
          onNavigate("overview");
        }}
      >
        <BrandMark />
        <span>{productName}</span>
      </a>

      <nav className="sidebar-nav" aria-label="Sections">
        <span className="sidebar-section-label">Workspace</span>
        {SECTIONS.map((s) => {
          const active = activeSection === s.id;
          return (
            <a
              key={s.id}
              href={`#${s.id}`}
              className={`sidebar-item focus-ring ${active ? "is-active" : ""}`}
              aria-current={active ? "location" : undefined}
              onClick={(e) => {
                e.preventDefault();
                onNavigate(s.id);
              }}
            >
              <s.icon
                className="sidebar-item-icon"
                size={16}
                strokeWidth={1.75}
                aria-hidden
              />
              <span className="sidebar-item-copy">
                <span className="sidebar-item-label">{s.label}</span>
                <span className="sidebar-item-desc">{s.description}</span>
              </span>
            </a>
          );
        })}
      </nav>

      <div className="sidebar-recent">
        <span className="sidebar-section-label" id="sidebar-recent-label">
          Recent
        </span>
        {recentState === "loading" ? (
          <p className="sidebar-empty">Loading…</p>
        ) : recentState === "down" ? (
          <p className="sidebar-empty">Backend offline</p>
        ) : recent.length === 0 ? (
          <p className="sidebar-empty">No recent notes</p>
        ) : (
          <ul aria-labelledby="sidebar-recent-label">
            {recent.map((n) => {
              const active = selectedNoteId === n.id;
              return (
                <li key={n.id}>
                  <button
                    type="button"
                    className={`sidebar-note focus-ring ${active ? "is-active" : ""}`}
                    aria-pressed={active}
                    title={n.path}
                    onClick={() => onOpenNote(n.id)}
                  >
                    <span className="truncate">{n.title}</span>
                    <span className="sidebar-note-folder truncate">
                      {n.path.split("/")[0]}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="sidebar-status" role="status">
        <span className={`status-dot ${backend}`} aria-hidden />
        <span>{backendLabel[backend]}</span>
      </div>
    </aside>
  );
}
