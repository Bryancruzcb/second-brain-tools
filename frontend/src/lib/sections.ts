import {
  LayoutDashboard,
  MessageCircle,
  Network,
  Wrench,
  type LucideIcon,
} from "lucide-react";

/** One continuous workspace: each id is a `<section>` on the page, in order. */
export type SectionId = "overview" | "map" | "health" | "ask";

export type SectionLink = {
  id: SectionId;
  label: string;
  description: string;
  icon: LucideIcon;
};

export const SECTIONS: SectionLink[] = [
  {
    id: "overview",
    label: "Overview",
    description: "Recent notes and vault status",
    icon: LayoutDashboard,
  },
  {
    id: "map",
    label: "Map",
    description: "How your notes connect",
    icon: Network,
  },
  {
    id: "health",
    label: "Repair",
    description: "Broken links, orphans, tags",
    icon: Wrench,
  },
  {
    id: "ask",
    label: "Ask",
    description: "Grounded answers from Qwen",
    icon: MessageCircle,
  },
];
