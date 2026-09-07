import type { GraphNode, HealthIssue, Note } from "@/types";

export const productName = "Atlas";
export const productTagline = "Atlas";

export const notes: Note[] = [
  {
    id: "n1",
    title: "Continuous capture loops",
    path: "Systems/Continuous capture loops.md",
    tags: ["systems", "workflow"],
    excerpt: "Capture once, revisit without losing context.",
    body: `Principles
• Capture in the moment
• Link while the idea is fresh
• Review weekly

Open questions
• How often to promote inbox scraps?
• Folder vs tag for systems notes?`,
    updatedAt: "2026-09-05T18:22:00Z",
    links: ["n2", "n4"],
    backlinks: ["n3"],
  },
  {
    id: "n2",
    title: "Vault health taxonomy",
    path: "Systems/Vault health taxonomy.md",
    tags: ["maintenance", "graph"],
    excerpt: "Broken links, orphans, and tagless notes.",
    body: `Broken link → retarget or create
Orphan → link from a hub
Tagless → add tags`,
    updatedAt: "2026-09-04T11:04:00Z",
    links: ["n1"],
    backlinks: ["n1", "n5"],
  },
  {
    id: "n3",
    title: "Local Qwen prompts",
    path: "AI/Local Qwen prompts.md",
    tags: ["ai", "prompts"],
    excerpt: "Local prompts for vault Q&A.",
    body: `Keep prompts short.
Pass only the active note plus a couple of neighbors.
Prefer quotes over paraphrase when citing.`,
    updatedAt: "2026-09-03T09:41:00Z",
    links: ["n1"],
    backlinks: [],
  },
  {
    id: "n4",
    title: "Graph reading modes",
    path: "Graph/Graph reading modes.md",
    tags: ["graph", "ux"],
    excerpt: "Neighborhood, path, and cluster views.",
    body: `1. Neighborhood — nearby notes
2. Path — route between two notes
3. Cluster — by tag or folder`,
    updatedAt: "2026-09-02T16:18:00Z",
    links: ["n2"],
    backlinks: ["n1"],
  },
  {
    id: "n5",
    title: "Meeting: Atlas redesign sync",
    path: "Meetings/2026-09-01 Atlas redesign sync.md",
    tags: [],
    excerpt: "Decisions on product marketing surface and inline note expansion.",
    body: `• Light Apple-soft field with one indigo accent
• Browser-frame product mock as the hero
• Replace editorial chapters with portfolio-style bento
• Primary motion is scroll and horizontal reel`,
    updatedAt: "2026-09-01T20:05:00Z",
    links: ["n2"],
    backlinks: [],
  },
  {
    id: "n6",
    title: "Inbox scrap — random URL",
    path: "Inbox/random-url.md",
    tags: [],
    excerpt: "Unprocessed capture with a dangling wiki-link.",
    body: `Saw [[Missing note about spaced repetition]] — need to create or retarget.

Also orphaned from hubs. Sitting in Inbox since late August.`,
    updatedAt: "2026-08-28T07:12:00Z",
    links: [],
    backlinks: [],
  },
  {
    id: "n7",
    title: "Weekly review template",
    path: "Templates/Weekly review.md",
    tags: ["template"],
    excerpt: "Template without inbound links from active journals.",
    body: `Wins
Friction
Next commitments

Link this from Journals/MOC so it stops being an orphan.`,
    updatedAt: "2026-08-20T14:00:00Z",
    links: [],
    backlinks: [],
  },
  {
    id: "n8",
    title: "Spaced repetition margins",
    path: "Learning/Spaced repetition margins.md",
    tags: ["learning", "memory"],
    excerpt: "When to leave a note alone vs. resurfacing it for review.",
    body: `Margins matter more than intervals.
If a note was touched this week, don't force a review card.
If it has zero backlinks and no tags, resurfacing is a repair cue.`,
    updatedAt: "2026-09-05T12:00:00Z",
    links: ["n1"],
    backlinks: [],
  },
];

export const recentNoteIds = ["n1", "n8", "n2", "n3", "n4", "n5"];

export const healthIssues: HealthIssue[] = [
  {
    id: "h1",
    kind: "broken-link",
    noteId: "n6",
    title: "Inbox scrap — random URL",
    detail: "Points at a missing note about spaced repetition.",
    action: "Retarget → Spaced repetition margins",
  },
  {
    id: "h2",
    kind: "broken-link",
    noteId: "n3",
    title: "Local Qwen prompts",
    detail: "Stale alias: Continuous capture loops (case mismatch).",
    action: "Normalize wiki-link",
  },
  {
    id: "h3",
    kind: "orphan",
    noteId: "n6",
    title: "Inbox scrap — random URL",
    detail: "Zero backlinks · not cited by any MOC.",
    action: "Link from Inbox hub",
  },
  {
    id: "h4",
    kind: "orphan",
    noteId: "n7",
    title: "Weekly review template",
    detail: "Zero backlinks · templates folder is silent.",
    action: "Cite from Journals/MOC",
  },
  {
    id: "h5",
    kind: "tagless",
    noteId: "n5",
    title: "Meeting: Atlas redesign sync",
    detail: "No tags. Likely meetings · design · decisions.",
    action: "Apply suggested tags",
  },
  {
    id: "h6",
    kind: "tagless",
    noteId: "n6",
    title: "Inbox scrap — random URL",
    detail: "No tags. Likely inbox · capture.",
    action: "Apply suggested tags",
  },
];

export const graphNodes: GraphNode[] = [
  { id: "n1", x: 270, y: 155, r: 10, cluster: "systems" },
  { id: "n2", x: 355, y: 118, r: 8, cluster: "systems" },
  { id: "n3", x: 150, y: 240, r: 7, cluster: "ai" },
  { id: "n4", x: 495, y: 220, r: 8, cluster: "graph" },
  { id: "n5", x: 360, y: 290, r: 6, cluster: "meetings" },
  { id: "n6", x: 85, y: 118, r: 6, cluster: "inbox" },
  { id: "n7", x: 565, y: 138, r: 6, cluster: "templates" },
  { id: "n8", x: 195, y: 78, r: 7, cluster: "learning" },
];

export const graphEdges: [string, string][] = [
  ["n1", "n2"],
  ["n1", "n4"],
  ["n1", "n3"],
  ["n1", "n8"],
  ["n2", "n5"],
  ["n2", "n4"],
  ["n8", "n2"],
];

export const composePrompts = [
  "Summarize continuous capture loops",
  "List broken links to fix",
  "Notes related to vault health",
];
