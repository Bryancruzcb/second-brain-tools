/** Sidebar order; ⌘1–4 follow this order. */
export const VIEWS = ["notes", "map", "ask", "health"] as const;
export type ViewId = (typeof VIEWS)[number];

export const VIEW_META: Record<
  ViewId,
  { label: string; shortcut: string; description: string }
> = {
  notes: {
    label: "Notes",
    shortcut: "1",
    description: "Browse and read your notes",
  },
  map: {
    label: "Map",
    shortcut: "2",
    description: "See how your notes connect",
  },
  ask: {
    label: "Ask",
    shortcut: "3",
    description: "Ask questions about your notes",
  },
  health: {
    label: "Health",
    shortcut: "4",
    description: "Quick fixes for links, tags and search",
  },
};

/** Legacy view keys that were renamed. "repair" became "health". */
const LEGACY_VIEWS: Record<string, ViewId> = {
  repair: "health",
};

/** Map a stored, hashed or legacy view key onto a current ViewId (or null). */
export function normalizeView(value: string | null | undefined): ViewId | null {
  if (!value) return null;
  const key = value.trim().toLowerCase().replace(/^#/, "");
  if ((VIEWS as readonly string[]).includes(key)) return key as ViewId;
  return LEGACY_VIEWS[key] ?? null;
}

export const VIEW_STORAGE_KEY = "atlas:view";

export const PRODUCT_NAME = "Atlas";
