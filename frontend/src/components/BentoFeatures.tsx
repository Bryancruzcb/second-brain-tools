"use client";

import { AskPanel } from "./AskPanel";
import { HealthPanel } from "./HealthPanel";
import { MapPanel } from "./MapPanel";
import type { SectionId } from "./TopNav";

type Props = {
  mapFocusId: string | null;
  askContextId: string | null;
  onMapNode: (id: string) => void;
  onHealthOpen: (noteId: string, issueId: string) => void;
  onClearAskContext: () => void;
  glowSection: SectionId | null;
};

export function BentoFeatures({
  mapFocusId,
  askContextId,
  onMapNode,
  onHealthOpen,
  onClearAskContext,
  glowSection,
}: Props) {
  return (
    <section className="mx-auto max-w-6xl px-6 pb-20 pt-4">
      <div className="bento-grid">
        <MapPanel
          activeId={mapFocusId}
          onNodeClick={onMapNode}
          sectionGlow={glowSection === "map"}
        />
        <HealthPanel
          onOpenNote={onHealthOpen}
          sectionGlow={glowSection === "health"}
        />
        <AskPanel
          contextNoteId={askContextId}
          onClearContext={onClearAskContext}
          sectionGlow={glowSection === "ask"}
        />
      </div>
    </section>
  );
}
