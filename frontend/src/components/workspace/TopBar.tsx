"use client";

import { CircleAlert, CircleCheck, Loader, Search, Telescope } from "lucide-react";
import { indexStatus } from "@/lib/status";
import { PRODUCT_NAME, TAB_ORDER, VIEW_META } from "@/lib/workspace";
import { useWorkspace } from "./context";

const STATUS_ICON = { ok: CircleCheck, wait: Loader, bad: CircleAlert } as const;

/** Brand, the four view tabs, the index status (outside Notes, which says it in its lead line) and search. */
export function TopBar() {
  const { view, setView, ready, setCommandOpen } = useWorkspace();
  const status = indexStatus(ready);
  const StatusIcon = STATUS_ICON[status.tone];

  return (
    <header className="topbar">
      <div className="brand">
        <Telescope aria-hidden strokeWidth={2} />
        <span>{PRODUCT_NAME}</span>
      </div>
      <nav aria-label="Views">
        <ul className="tabs">
          {TAB_ORDER.map((id) => {
            const meta = VIEW_META[id];
            return (
              <li key={id}>
                <button
                  type="button"
                  className="tab"
                  aria-current={view === id ? "page" : undefined}
                  title={`${meta.label} (Ctrl ${meta.shortcut})`}
                  onClick={() => setView(id)}
                >
                  {meta.label}
                  <kbd>Ctrl {meta.shortcut}</kbd>
                </button>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="topbar-end">
        {view !== "notes" && (
          <p
            className={`index-status mono ${status.tone}`}
            role="status"
            title={status.detail}
            style={{ margin: 0 }}
          >
            <StatusIcon className="icon" aria-hidden strokeWidth={2} />
            <span className="label">{status.text}</span>
          </p>
        )}
        <button
          type="button"
          className="search-trigger"
          aria-label="Search notes (Ctrl K)"
          aria-haspopup="dialog"
          onClick={() => setCommandOpen(true)}
        >
          <Search className="icon" aria-hidden strokeWidth={2} />
          <span className="label">Search</span>
          <span className="kbd">Ctrl K</span>
        </button>
      </div>
    </header>
  );
}
