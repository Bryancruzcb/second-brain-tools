"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BentoFeatures } from "./BentoFeatures";
import { FooterStrip } from "./FooterStrip";
import { Hero } from "./Hero";
import { RecentReel } from "./RecentReel";
import { TopNav, type SectionId } from "./TopNav";

const GLOW_MS = 1400;

export function ProductPage() {
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);
  const [repairIssueId, setRepairIssueId] = useState<string | null>(null);
  const [mapFocusId, setMapFocusId] = useState<string | null>(null);
  const [askContextId, setAskContextId] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<SectionId | null>(null);
  const [glowSection, setGlowSection] = useState<SectionId | null>(null);
  const glowTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (glowTimer.current) clearTimeout(glowTimer.current);
    };
  }, []);

  const pulseGlow = useCallback((section: SectionId) => {
    setActiveSection(section);
    setGlowSection(section);
    if (glowTimer.current) clearTimeout(glowTimer.current);
    glowTimer.current = setTimeout(() => setGlowSection(null), GLOW_MS);
  }, []);

  const onNavigate = useCallback(
    (section: SectionId) => {
      pulseGlow(section);
      const el = document.getElementById(section);
      el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    },
    [pulseGlow],
  );

  const onSelectNote = useCallback((id: string | null) => {
    setSelectedNoteId(id);
    setRepairIssueId(null);
    if (id) setMapFocusId(id);
  }, []);

  const onMapNode = useCallback((id: string) => {
    setMapFocusId(id);
    setAskContextId(id);
    setSelectedNoteId(id);
    setRepairIssueId(null);
    pulseGlow("notes");
    document.getElementById("notes")?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  }, [pulseGlow]);

  const onHealthOpen = useCallback(
    (noteId: string, issueId: string) => {
      setSelectedNoteId(noteId);
      setRepairIssueId(issueId);
      setMapFocusId(noteId);
      pulseGlow("notes");
      document.getElementById("notes")?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    },
    [pulseGlow],
  );

  const onClearAskContext = useCallback(() => {
    setAskContextId(null);
  }, []);

  return (
    <div id="top" className="min-h-screen bg-page">
      <TopNav activeSection={activeSection} onNavigate={onNavigate} />
      <main>
        <Hero />
        <RecentReel
          selectedId={selectedNoteId}
          repairIssueId={repairIssueId}
          onSelect={onSelectNote}
          sectionGlow={glowSection === "notes"}
        />
        <BentoFeatures
          mapFocusId={mapFocusId}
          askContextId={askContextId}
          onMapNode={onMapNode}
          onHealthOpen={onHealthOpen}
          onClearAskContext={onClearAskContext}
          glowSection={glowSection}
        />
      </main>
      <FooterStrip />
    </div>
  );
}
