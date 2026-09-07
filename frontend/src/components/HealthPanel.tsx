"use client";

import { ChevronRight } from "lucide-react";
import { healthIssues } from "@/data/mock";
import { GlowOutline } from "./GlowOutline";

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
  onOpenNote: (noteId: string, issueId: string) => void;
  sectionGlow?: boolean;
};

export function HealthPanel({ onOpenNote, sectionGlow }: Props) {
  const counts = {
    broken: healthIssues.filter((h) => h.kind === "broken-link").length,
    orphan: healthIssues.filter((h) => h.kind === "orphan").length,
    tagless: healthIssues.filter((h) => h.kind === "tagless").length,
  };
  const toFix = counts.broken + counts.orphan + counts.tagless;

  return (
    <GlowOutline
      id="health"
      glow={sectionGlow}
      radius={18}
      className="h-full"
    >
      <div className="card-elevated flex h-full min-h-[200px] flex-col overflow-hidden">
        <div className="flex items-center justify-between border-b border-hairline px-5 py-4">
          <div className="min-w-0">
            <h3 className="text-[16px] font-medium tracking-[-0.02em]">Repair</h3>
            <p className="mt-0.5 text-[12px] font-medium text-muted">
              Broken links, orphans, missing tags
            </p>
          </div>
          <span className="rounded-full bg-[var(--accent-softer)] px-2.5 py-1 text-[12px] font-medium text-[var(--accent)]">
            {toFix} to fix
          </span>
        </div>
        <ul className="flex-1 divide-y divide-hairline overflow-y-auto">
          {healthIssues.map((issue) => (
            <li key={issue.id}>
              <button
                type="button"
                className="group flex w-full items-start gap-3 px-5 py-3.5 text-left transition hover:bg-[#fafafa] focus-ring"
                onClick={() => onOpenNote(issue.noteId, issue.id)}
              >
                <span className={`status-pill mt-0.5 shrink-0 ${kindClass[issue.kind]}`}>
                  {kindLabel[issue.kind]}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13.5px] font-medium tracking-[-0.015em] text-ink">
                    {issue.title}
                  </span>
                  <span className="mt-0.5 block text-[12px] leading-snug text-muted">
                    {issue.detail}
                  </span>
                  <span className="mt-1 block text-[12px] font-medium text-[var(--accent)]">
                    {issue.action}
                  </span>
                </span>
                <span className="mt-0.5 inline-flex shrink-0 items-center gap-0.5 text-[12px] font-medium text-muted transition group-hover:text-[var(--accent)]">
                  Open
                  <ChevronRight className="h-3.5 w-3.5" strokeWidth={2.25} />
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </GlowOutline>
  );
}
