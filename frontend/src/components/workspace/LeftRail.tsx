"use client";

import { FileText, Map, MessageSquareText, Wrench } from "lucide-react";
import { PRODUCT_NAME, VIEW_META, type ViewId } from "@/lib/workspace";
import { useWorkspace } from "./context";

const ICONS: Record<ViewId, typeof FileText> = {
  notes: FileText,
  map: Map,
  repair: Wrench,
  ask: MessageSquareText,
};

export function LeftRail() {
  const { view, setView, ready } = useWorkspace();
  const views = Object.keys(VIEW_META) as ViewId[];

  const status = !ready
    ? "Checking backend…"
    : ready.ready
      ? "Index ready"
      : "Loading retrieval…";

  return (
    <aside className="flex flex-col border-r border-hairline bg-page max-md:order-2 max-md:flex-row max-md:border-r-0 max-md:border-t">
      <div className="flex items-center gap-2 px-4 py-4 max-md:hidden">
        <span
          aria-hidden
          className="flex h-6 w-6 items-center justify-center rounded-[7px]"
          style={{ background: "var(--accent)" }}
        >
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <circle cx="6" cy="6" r="2.2" fill="#0D1117" />
            <circle cx="2.2" cy="3.2" r="1.1" fill="#0D1117" opacity="0.85" />
            <circle cx="9.5" cy="3.8" r="1.1" fill="#0D1117" opacity="0.85" />
            <circle cx="3" cy="9" r="1.1" fill="#0D1117" opacity="0.85" />
          </svg>
        </span>
        <span className="text-[14px] font-semibold tracking-[-0.02em]">
          {PRODUCT_NAME}
        </span>
      </div>

      <nav
        aria-label="Workspace"
        className="flex flex-1 flex-col gap-0.5 px-2 max-md:flex-row max-md:justify-around max-md:px-1 max-md:py-1"
      >
        {views.map((id) => {
          const Icon = ICONS[id];
          const active = view === id;
          const meta = VIEW_META[id];
          return (
            <button
              key={id}
              type="button"
              aria-current={active ? "page" : undefined}
              className={`focus-ring flex items-center gap-2.5 rounded-[7px] px-2.5 py-2 text-left text-[13px] font-medium max-md:flex-1 max-md:flex-col max-md:gap-0.5 max-md:px-1 max-md:text-[11px] ${
                active
                  ? "bg-elevated text-ink"
                  : "text-muted hover:bg-elevated hover:text-ink"
              }`}
              onClick={() => setView(id)}
            >
              <Icon
                className="h-4 w-4 shrink-0"
                strokeWidth={1.75}
                color={active ? "var(--accent)" : "currentColor"}
              />
              <span className="flex-1">{meta.label}</span>
              <span className="mono hidden text-[10px] text-muted md:inline">
                ⌘{meta.shortcut}
              </span>
            </button>
          );
        })}
      </nav>

      <p
        className="mono px-4 py-3 text-[10px] text-muted max-md:hidden"
        role="status"
        title={
          ready?.components
            ? Object.entries(ready.components)
                .map(([k, v]) => `${k}: ${v ? "on" : "off"}`)
                .join("\n")
            : undefined
        }
      >
        {status}
      </p>
    </aside>
  );
}
