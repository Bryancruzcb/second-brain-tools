"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { prefersReducedMotion, scrollToId } from "@/lib/scroll";
import { SECTIONS, type SectionId } from "@/lib/sections";
import { AskPanel } from "./AskPanel";
import { FooterStrip } from "./FooterStrip";
import { HealthPanel } from "./HealthPanel";
import { MapPanel } from "./MapPanel";
import { Overview } from "./Overview";
import { RecentReel } from "./RecentReel";
import { Sidebar } from "./Sidebar";
import { TopNav } from "./TopNav";

/** A section is "current" once its top crosses this line below the viewport top. */
const ACTIVE_LINE_PX = 180;
/**
 * After a nav click, hold that section active while the smooth scroll passes
 * the others. `scrollend` releases the hold early where the browser fires it;
 * this is the ceiling for browsers that do not.
 */
const NAV_LOCK_MS = 1500;
/** Within this many px of the document end, the last section counts as current even if short. */
const BOTTOM_SLACK_PX = 48;

export function ProductPage() {
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);
  const [repairIssueId, setRepairIssueId] = useState<string | null>(null);
  const [mapFocusId, setMapFocusId] = useState<string | null>(null);
  const [askContextId, setAskContextId] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<SectionId | null>(null);
  const navLock = useRef<{ target: SectionId; until: number } | null>(null);

  // Scroll-spy: the last section whose top has passed the active line wins.
  useEffect(() => {
    let frame = 0;
    const update = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        const lock = navLock.current;
        if (lock && performance.now() < lock.until) {
          setActiveSection(lock.target);
          return;
        }
        navLock.current = null;
        const line = Math.min(ACTIVE_LINE_PX, window.innerHeight * 0.25);
        let next: SectionId = SECTIONS[0].id;
        for (const s of SECTIONS) {
          const el = document.getElementById(s.id);
          if (el && el.getBoundingClientRect().top <= line) next = s.id;
        }
        const atBottom =
          window.innerHeight + window.scrollY >=
          document.documentElement.scrollHeight - BOTTOM_SLACK_PX;
        if (atBottom) next = SECTIONS[SECTIONS.length - 1].id;
        setActiveSection(next);
      });
    };
    const settled = () => {
      navLock.current = null;
      update();
    };
    update();
    window.addEventListener("scroll", update, { passive: true });
    window.addEventListener("scrollend", settled);
    window.addEventListener("resize", update);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("scroll", update);
      window.removeEventListener("scrollend", settled);
      window.removeEventListener("resize", update);
    };
  }, []);

  const onNavigate = useCallback((section: SectionId) => {
    navLock.current = {
      target: section,
      until: performance.now() + (prefersReducedMotion() ? 0 : NAV_LOCK_MS),
    };
    setActiveSection(section);
    scrollToId(section);
    // Keep the section in the URL so a reload or shared link lands on it,
    // without pushing a history entry per click.
    window.history.replaceState(null, "", `#${section}`);
  }, []);

  const onSelectNote = useCallback((id: string | null) => {
    setSelectedNoteId(id);
    setRepairIssueId(null);
    if (id) setMapFocusId(id);
  }, []);

  /** Sidebar recent list: always select, and bring the reader into view. */
  const onOpenRecent = useCallback(
    (id: string) => {
      onSelectNote(id);
      scrollToId("notes");
    },
    [onSelectNote],
  );

  const onMapNode = useCallback((id: string) => {
    setMapFocusId(id);
    setAskContextId(id);
    setSelectedNoteId(id);
    setRepairIssueId(null);
    scrollToId("notes");
  }, []);

  const onHealthOpen = useCallback((noteId: string, issueId: string) => {
    setSelectedNoteId(noteId);
    setRepairIssueId(issueId);
    setMapFocusId(noteId);
    scrollToId("notes");
  }, []);

  const onClearAskContext = useCallback(() => {
    setAskContextId(null);
  }, []);

  return (
    <div className="app-shell">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <Sidebar
        activeSection={activeSection}
        selectedNoteId={selectedNoteId}
        onNavigate={onNavigate}
        onOpenNote={onOpenRecent}
      />
      <div className="app-main">
        <TopNav activeSection={activeSection} onNavigate={onNavigate} />
        <main id="main" className="journey" tabIndex={-1}>
          <section
            id="overview"
            className="journey-section"
            aria-labelledby="overview-title"
          >
            <Overview />
            <RecentReel
              selectedId={selectedNoteId}
              repairIssueId={repairIssueId}
              onSelect={onSelectNote}
            />
          </section>
          <section id="map" className="journey-section" aria-labelledby="map-title">
            <MapPanel activeId={mapFocusId} onNodeClick={onMapNode} />
          </section>
          <section
            id="health"
            className="journey-section"
            aria-labelledby="health-title"
          >
            <HealthPanel onOpenNote={onHealthOpen} />
          </section>
          <section id="ask" className="journey-section" aria-labelledby="ask-title">
            <AskPanel
              contextNoteId={askContextId}
              onClearContext={onClearAskContext}
            />
          </section>
        </main>
        <FooterStrip />
      </div>
    </div>
  );
}
