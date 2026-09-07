"use client";

import { useEffect, useState } from "react";
import { fetchRecent, recentToNote } from "@/lib/api";
import type { Note } from "@/types";

export function MiniWorkspace() {
  const [sidebarNotes, setSidebarNotes] = useState<Note[]>([]);
  const [status, setStatus] = useState<"loading" | "ok" | "down">("loading");

  useEffect(() => {
    let cancelled = false;
    fetchRecent()
      .then((res) => {
        if (cancelled) return;
        setSidebarNotes((res.notes || []).slice(0, 5).map(recentToNote));
        setStatus("ok");
      })
      .catch(() => {
        if (!cancelled) setStatus("down");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const active = sidebarNotes[0];

  return (
    <div className="flex h-[420px] bg-white text-[13px] leading-snug sm:h-[460px]">
      <aside className="hidden w-[200px] shrink-0 border-r border-hairline bg-[#fafafa] md:flex md:flex-col">
        <div className="flex items-center justify-between px-3.5 py-3">
          <span className="text-[12px] font-semibold tracking-[-0.01em] text-ink">
            Notes
          </span>
          <span className="mono text-[10px] text-muted">⌘K</span>
        </div>
        <div className="px-2 pb-2">
          <div className="flex h-8 items-center gap-2 rounded-lg border border-hairline bg-white px-2.5 text-[12px] text-muted">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <circle cx="5" cy="5" r="3.5" stroke="currentColor" strokeWidth="1.2" />
              <path d="M8 8l2.2 2.2" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            </svg>
            Search…
          </div>
        </div>
        <div className="flex-1 overflow-hidden px-1.5">
          {status === "loading" && (
            <div className="px-2.5 py-2 text-[12px] text-muted">Loading…</div>
          )}
          {status === "down" && (
            <div className="px-2.5 py-2 text-[12px] text-muted">Backend offline</div>
          )}
          {sidebarNotes.map((n, i) => (
            <div
              key={n.id}
              className={`mb-0.5 rounded-lg px-2.5 py-2 ${
                i === 0
                  ? "bg-[var(--accent-soft)] text-[var(--accent)]"
                  : "text-ink/80"
              }`}
            >
              <div className="truncate text-[12.5px] font-medium tracking-[-0.01em]">
                {n.title}
              </div>
              <div className="mt-0.5 truncate text-[11px] text-muted">
                {n.path.split("/")[0]}
              </div>
            </div>
          ))}
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col border-r border-hairline">
        <div className="flex items-center justify-between border-b border-hairline px-5 py-3">
          <div className="min-w-0">
            <div className="truncate text-[14px] font-semibold tracking-[-0.02em]">
              {active?.title || (status === "down" ? "Vault offline" : "Atlas")}
            </div>
            <div className="mono mt-0.5 truncate text-[11px] text-muted">
              {active?.path || "localhost:3000/vault"}
            </div>
          </div>
        </div>
        <div className="flex-1 overflow-hidden px-5 py-4">
          <div className="space-y-2 text-[13px] leading-relaxed text-muted">
            {active?.excerpt ? (
              <p className="line-clamp-6 text-ink/80">{active.excerpt}</p>
            ) : (
              <>
                <p className="font-medium text-ink/80">Live vault</p>
                <p>• Recent notes from FastAPI</p>
                <p>• Map · Repair · Ask below</p>
              </>
            )}
          </div>
        </div>
      </section>

      <aside className="hidden w-[200px] shrink-0 flex-col bg-[#fbfbfd] lg:flex">
        <div className="border-b border-hairline px-3.5 py-3 text-[12px] font-semibold tracking-[-0.01em]">
          Map
        </div>
        <div className="relative flex-1 p-2">
          <svg viewBox="0 0 180 280" className="h-full w-full">
            <line x1="90" y1="120" x2="50" y2="60" stroke="#D2D2D7" strokeWidth="1.2" />
            <line x1="90" y1="120" x2="140" y2="70" stroke="#D2D2D7" strokeWidth="1.2" />
            <line x1="90" y1="120" x2="40" y2="190" stroke="#D2D2D7" strokeWidth="1.2" />
            <line x1="90" y1="120" x2="145" y2="200" stroke="#D2D2D7" strokeWidth="1.2" />
            <line x1="90" y1="120" x2="95" y2="230" stroke="#D2D2D7" strokeWidth="1.2" />
            <circle cx="90" cy="120" r="9" fill="#5E6AD2" />
            <circle cx="50" cy="60" r="6" fill="#5E6AD2" fillOpacity="0.55" />
            <circle cx="140" cy="70" r="6" fill="#5E6AD2" fillOpacity="0.45" />
            <circle cx="40" cy="190" r="5.5" fill="#5E6AD2" fillOpacity="0.4" />
            <circle cx="145" cy="200" r="5.5" fill="#5E6AD2" fillOpacity="0.35" />
            <circle cx="95" cy="230" r="5" fill="#5E6AD2" fillOpacity="0.3" />
            <text x="90" y="145" textAnchor="middle" fill="#1D1D1F" fontSize="9" fontWeight="500">
              Vault
            </text>
          </svg>
        </div>
      </aside>
    </div>
  );
}
