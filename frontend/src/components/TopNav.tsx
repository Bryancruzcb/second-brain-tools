"use client";

import { productName } from "@/data/mock";
import { SECTIONS, type SectionId } from "@/lib/sections";
import { BrandMark } from "./BrandMark";
import { GlowOutline } from "./GlowOutline";

type Props = {
  activeSection: SectionId | null;
  onNavigate: (section: SectionId) => void;
};

/** Sticky top bar for viewports too narrow for the sidebar (below `lg`). */
export function TopNav({ activeSection, onNavigate }: Props) {
  return (
    <header className="sticky top-0 z-40 border-b border-hairline/80 bg-[color-mix(in_srgb,var(--page)_82%,transparent)] backdrop-blur-xl lg:hidden">
      <div className="flex h-14 items-center justify-between gap-4 px-4 sm:px-6">
        <a
          href="#overview"
          className="flex shrink-0 items-center gap-2 rounded-md focus-ring"
          onClick={(e) => {
            e.preventDefault();
            onNavigate("overview");
          }}
        >
          <BrandMark />
          <span className="text-[15px] font-semibold tracking-[-0.02em] text-ink">
            {productName}
          </span>
        </a>

        <nav
          className="topnav-links -mx-3 -my-2.5 flex min-w-0 items-center gap-5 overflow-x-auto px-3 py-2.5"
          aria-label="Sections"
        >
          {SECTIONS.map((l) => {
            const isActive = activeSection === l.id;
            return (
              <GlowOutline key={l.id} compact radius={8}>
                <a
                  href={`#${l.id}`}
                  className={`nav-link whitespace-nowrap rounded focus-ring ${isActive ? "is-active" : ""}`}
                  aria-current={isActive ? "location" : undefined}
                  onClick={(e) => {
                    e.preventDefault();
                    onNavigate(l.id);
                  }}
                >
                  {l.label}
                </a>
              </GlowOutline>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
