/** Which side panes of the Notes view are open. Folding both leaves just the map. */
export type Panes = Readonly<{ recent: boolean; reader: boolean }>;

export const ALL_OPEN: Panes = { recent: true, reader: true };
export const MAP_ONLY: Panes = { recent: false, reader: false };

/** Read the saved choice; anything missing or unreadable means open. */
export function parsePanes(raw: string | null): Panes {
  if (!raw) return ALL_OPEN;
  try {
    const saved: unknown = JSON.parse(raw);
    if (typeof saved !== "object" || saved === null) return ALL_OPEN;
    const { recent, reader } = saved as Record<string, unknown>;
    return { recent: recent !== false, reader: reader !== false };
  } catch {
    return ALL_OPEN;
  }
}

export const isMapOnly = (p: Panes): boolean => !p.recent && !p.reader;

/** The "Map only" button: fold both panes, or open both again when they already are folded. */
export const toggleMapOnly = (p: Panes): Panes => (isMapOnly(p) ? ALL_OPEN : MAP_ONLY);
