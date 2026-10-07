export const VIEWS = ["notes", "map", "repair", "ask"] as const;
export type ViewId = (typeof VIEWS)[number];

export const VIEW_META: Record<
  ViewId,
  { label: string; shortcut: string; description: string }
> = {
  notes: {
    label: "Notes",
    shortcut: "1",
    description: "Recent notes and the inspector",
  },
  map: {
    label: "Map",
    shortcut: "2",
    description: "Vault neighborhood graph",
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

export const PRODUCT_NAME = "Atlas";
