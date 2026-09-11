"use client";

import { useEffect, useState } from "react";
import { productName } from "@/data/mock";
import { fetchHealthCached } from "@/lib/api";

export function Overview() {
  const [statusLine, setStatusLine] = useState("Loading vault…");

  useEffect(() => {
    let cancelled = false;
    fetchHealthCached()
      .then((res) => {
        if (cancelled) return;
        const d = res.data || {};
        const issues =
          (d.broken_links?.length || 0) +
          (d.orphaned_notes?.length || 0) +
          (d.tagless_notes?.length || 0);
        const parts: string[] = [];
        if (d.total_notes != null)
          parts.push(`${d.total_notes.toLocaleString("en-US")} notes`);
        if (d.total_links != null)
          parts.push(`${d.total_links.toLocaleString("en-US")} links`);
        parts.push(res.is_scanning ? "scan in progress" : `${issues} to repair`);
        setStatusLine(parts.join(" · "));
      })
      .catch(() => {
        if (!cancelled)
          setStatusLine("Backend unreachable. Start FastAPI on :8000 for live data.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <header className="overview-header">
      <h1
        id="overview-title"
        className="text-[34px] font-medium leading-[1.1] tracking-[-0.03em] text-ink sm:text-[40px]"
      >
        {productName}
      </h1>
      <p className="mt-3 max-w-2xl text-[16px] leading-relaxed text-muted">
        Your Obsidian vault on this machine. Scroll through recent notes, the
        link map, the repair queue, and grounded answers, or jump with the
        sidebar.
      </p>
      <p className="mono mt-4 text-[12px] text-muted" aria-live="polite">
        {statusLine}
      </p>
    </header>
  );
}
