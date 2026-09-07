"use client";

import { productName } from "@/data/mock";
import { GlowOutline } from "./GlowOutline";

export type SectionId = "notes" | "map" | "health" | "ask";

const links: { label: string; id: SectionId }[] = [
  { label: "Notes", id: "notes" },
  { label: "Map", id: "map" },
  { label: "Repair", id: "health" },
  { label: "Ask", id: "ask" },
];

type Props = {
  activeSection: SectionId | null;
  onNavigate: (section: SectionId) => void;
};

export function TopNav({ activeSection, onNavigate }: Props) {
  return (
    <header className="sticky top-0 z-40 border-b border-hairline/80 bg-[color-mix(in_srgb,var(--page)_82%,transparent)] backdrop-blur-xl">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
        <a href="#top" className="flex items-center gap-2 focus-ring rounded-md">
          <span
            aria-hidden
            className="flex h-6 w-6 items-center justify-center rounded-[7px]"
            style={{ background: "var(--accent)" }}
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <circle cx="6" cy="6" r="2.2" fill="white" />
              <circle cx="2.2" cy="3.2" r="1.1" fill="white" opacity="0.85" />
              <circle cx="9.5" cy="3.8" r="1.1" fill="white" opacity="0.85" />
              <circle cx="3" cy="9" r="1.1" fill="white" opacity="0.85" />
              <path
                d="M3.2 3.5L5 5.2M8.8 4.2L6.8 5.4M3.6 8.4L5.2 6.6"
                stroke="white"
                strokeWidth="0.9"
                opacity="0.7"
              />
            </svg>
          </span>
          <span className="text-[15px] font-semibold tracking-[-0.02em] text-ink">
            {productName}
          </span>
        </a>

        <nav className="hidden items-center gap-5 sm:flex" aria-label="Primary">
          {links.map((l) => {
            const isActive = activeSection === l.id;
            return (
              <GlowOutline
                key={l.id}
                compact
                radius={8}
              >
                <a
                  href={`#${l.id}`}
                  className={`nav-link focus-ring rounded ${isActive ? "is-active" : ""}`}
                  aria-current={isActive ? "true" : undefined}
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

        <button
          type="button"
          className="btn-primary focus-ring"
          onClick={() => onNavigate("notes")}
        >
          Open vault
        </button>
      </div>
    </header>
  );
}
