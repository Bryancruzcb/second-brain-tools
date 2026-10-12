const TIME_ZONE = "America/Los_Angeles";
const DAY_MS = 1000 * 60 * 60 * 24;

export function formatTouched(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: TIME_ZONE,
  });
}

/** "Today", "Yesterday", "3d ago", then a short date. `nowMs` defaults to the clock. */
export function relativeDay(iso: string, nowMs: number = Date.now()): string {
  const d = new Date(iso);
  const diff = Math.floor((nowMs - d.getTime()) / DAY_MS);
  if (diff <= 0) return "Today";
  if (diff === 1) return "Yesterday";
  if (diff < 7) return `${diff}d ago`;
  return formatTouched(iso);
}

/** "Edited today, 08:40" / "Edited Sep 26, 06:50". */
export function editedPhrase(iso: string, nowMs: number = Date.now()): string {
  const day = relativeDay(iso, nowMs);
  const word = day === "Today" || day === "Yesterday" ? day.toLowerCase() : day;
  return `Edited ${word}, ${clockTime(iso)}`;
}

/** 24-hour clock time, e.g. "08:40". */
export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: TIME_ZONE,
  });
}

/** "just now", "5m ago", "2h ago", "3d ago", then a short date. */
export function askedAgo(epochSeconds: number, nowMs: number = Date.now()): string {
  const diff = Math.max(0, nowMs / 1000 - epochSeconds);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 7 * 86400) return `${Math.floor(diff / 86400)}d ago`;
  return formatTouched(new Date(epochSeconds * 1000).toISOString());
}
