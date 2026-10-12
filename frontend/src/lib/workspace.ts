export const VIEWS = ["notes", "map", "repair", "ask"] as const;
export type ViewId = (typeof VIEWS)[number];

export const VIEW_META: Record<
  ViewId,
  { label: string; shortcut: string; description: string }
> = {
  notes: {
    label: "Notes",
    shortcut: "1",
    description: "Recent notes, 3D vault map and reading pane",
  },
  map: {
    label: "Map",
    shortcut: "2",
    description: "3D map of the whole vault",
  },
  repair: {
    label: "Repair",
    shortcut: "3",
    description: "Broken links, orphans, tags",
  },
  ask: {
    label: "Ask",
    shortcut: "4",
    description: "Grounded questions via local Qwen",
  },
};

/** Display order of the tabs. The shortcuts keep their numbers (VIEWS order). */
export const TAB_ORDER: readonly ViewId[] = ["notes", "ask", "map", "repair"];

export const PRODUCT_NAME = "Atlas";
