import { folderCluster, isChatNote } from "./vaultPaths";

/**
 * The 3D vault map's data: every note and AI chat in /api/graph becomes a
 * point, folders become hub points, and the vault itself is the center.
 * Everything here is a calculation over plain data; VaultGlobe.tsx draws it.
 *
 * Each project keeps a copy of a chat under "<project>/AI Chat Links/" with
 * the same file name as the chat. Those copies are folded into the chat they
 * copy, so every chat is one point, linked to the projects it was filed under.
 */

export type GraphInputNode = Readonly<{ id: string; label?: string }>;
export type GraphInputEdge = Readonly<{ source: string; target: string; is_ghost?: boolean }>;

export type GlobeKind = "core" | "folder" | "chat" | "note";

export type GlobeNode = Readonly<{
  id: string;
  kind: GlobeKind;
  title: string;
  /** Vault-relative path ("" for the vault itself). */
  path: string;
  /** Folder depth: 0 for the vault, 1 for a top-level folder or a note at the vault root. */
  depth: number;
  /** The AI a chat came from ("Claude", "Codex", ...), null for everything else. */
  ai: string | null;
  /** The folder name the Map's folder filter uses. */
  cluster: string;
  /** YYYY-MM-DD when the file name starts with a date. */
  date: string | null;
  /** Links to and from other notes. */
  degree: number;
  /** Items directly inside a folder. */
  children: number;
  /** Project folders a chat was filed under. */
  topics: readonly string[];
}>;

export type GlobeLinkKind = "tree" | "link" | "topic";
export type GlobeLink = Readonly<{ source: string; target: string; kind: GlobeLinkKind }>;

export type Globe = Readonly<{
  nodes: readonly GlobeNode[];
  links: readonly GlobeLink[];
  counts: Readonly<{ chats: number; notes: number; folders: number; links: number }>;
  /** A chat's project copy -> the chat point it was folded into. */
  aliases: ReadonlyMap<string, string>;
}>;

export const CORE_ID = "vault:";
export const CHAT_ROOT = "05 AI Chats";
const CHAT_LINK_DIR = "AI Chat Links";
const FOLDER_PREFIX = "folder:";

const DATE_PREFIX = /^(\d{4}-\d{2}-\d{2})/;
const TITLE_DATE = /^\d{4}-\d{2}-\d{2}\s+-\s+/;
const TITLE_SHORT_ID = /\s+-\s+[0-9a-f]{6,12}$/i;

export const folderId = (path: string): string => (path ? FOLDER_PREFIX + path : CORE_ID);

const normalize = (id: string): string => id.replace(/\\/g, "/");

function baseName(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

function parentPath(path: string): string {
  const slash = path.lastIndexOf("/");
  return slash < 0 ? "" : path.slice(0, slash);
}

/** Every folder above a path, nearest first, not including the vault itself. */
function ancestors(path: string): string[] {
  const out: string[] = [];
  for (let p = parentPath(path); p; p = parentPath(p)) out.push(p);
  return out;
}

export function dateFromName(path: string): string | null {
  const found = DATE_PREFIX.exec(baseName(path));
  return found ? found[1] : null;
}

/** Drop the "2026-07-14 - " prefix and the " - 019ec7" session id that chat file names carry. */
export function cleanTitle(label: string | undefined, path: string): string {
  const raw = (label || baseName(path).replace(/\.md$/i, "")).trim();
  const cleaned = raw.replace(TITLE_DATE, "").replace(TITLE_SHORT_ID, "").trim();
  return cleaned || raw;
}

function isChatLinkCopy(path: string): boolean {
  return path.split("/").includes(CHAT_LINK_DIR);
}

/** The project a copy is filed under: the folder that holds its "AI Chat Links" folder. */
function topicOf(copyPath: string): string {
  const parts = copyPath.split("/");
  return parts.slice(0, parts.indexOf(CHAT_LINK_DIR)).join("/");
}

function aiOf(path: string): string | null {
  const parts = path.split("/");
  return parts[0] === CHAT_ROOT && parts.length > 2 ? parts[1] : null;
}

/** Map each chat copy to the chat it copies (same file name under 05 AI Chats). */
function foldCopies(ids: readonly string[]): { alias: Map<string, string>; topics: Map<string, string[]> } {
  const chatByName = new Map<string, string>();
  for (const id of [...ids].sort((a, b) => a.length - b.length || a.localeCompare(b))) {
    if (isChatNote(id) && !isChatLinkCopy(id) && !chatByName.has(baseName(id))) chatByName.set(baseName(id), id);
  }
  const alias = new Map<string, string>();
  const topics = new Map<string, string[]>();
  for (const id of ids) {
    if (!isChatLinkCopy(id)) continue;
    const chat = chatByName.get(baseName(id));
    if (!chat) continue;
    alias.set(id, chat);
    const topic = topicOf(id);
    const list = topics.get(chat) ?? [];
    if (topic && !list.includes(topic)) topics.set(chat, [...list, topic]);
  }
  return { alias, topics };
}

export function buildGlobe(inputNodes: readonly GraphInputNode[], inputEdges: readonly GraphInputEdge[]): Globe {
  const labels = new Map<string, string | undefined>();
  for (const n of inputNodes) {
    const id = normalize(n.id);
    if (id && !labels.has(id)) labels.set(id, n.label);
  }
  const ids = [...labels.keys()];
  const { alias, topics } = foldCopies(ids);
  const shown = ids.filter((id) => !alias.has(id));
  const shownSet = new Set(shown);
  const resolve = (id: string) => alias.get(id) ?? id;

  const linkKeys = new Set<string>();
  const links: GlobeLink[] = [];
  const degree = new Map<string, number>();
  for (const e of inputEdges) {
    if (e.is_ghost) continue;
    const a = resolve(normalize(e.source));
    const b = resolve(normalize(e.target));
    if (a === b || !shownSet.has(a) || !shownSet.has(b)) continue;
    const [source, target] = a < b ? [a, b] : [b, a];
    const key = `${source}\n${target}`;
    if (linkKeys.has(key)) continue;
    linkKeys.add(key);
    links.push({ source, target, kind: "link" });
    degree.set(source, (degree.get(source) ?? 0) + 1);
    degree.set(target, (degree.get(target) ?? 0) + 1);
  }

  const topicLinks: GlobeLink[] = [];
  for (const [chat, folders] of topics) {
    for (const folder of folders) topicLinks.push({ source: chat, target: folderId(folder), kind: "topic" });
  }

  const folders = new Set<string>();
  for (const id of shown) ancestors(id).forEach((f) => folders.add(f));
  for (const list of topics.values()) {
    for (const f of list) [f, ...ancestors(f)].forEach((p) => folders.add(p));
  }
  const folderList = [...folders].sort();

  const children = new Map<string, number>();
  const tree: GlobeLink[] = [];
  const addTree = (own: string, path: string) => {
    const parent = folderId(parentPath(path));
    tree.push({ source: own, target: parent, kind: "tree" });
    children.set(parent, (children.get(parent) ?? 0) + 1);
  };
  shown.forEach((id) => addTree(id, id));
  folderList.forEach((f) => addTree(folderId(f), f));

  const nodes: GlobeNode[] = [
    {
      id: CORE_ID, kind: "core", title: "Your vault", path: "", depth: 0, ai: null, cluster: "Vault",
      date: null, degree: 0, children: children.get(CORE_ID) ?? 0, topics: [],
    },
    ...folderList.map((f): GlobeNode => ({
      id: folderId(f), kind: "folder", title: baseName(f), path: f, depth: f.split("/").length,
      ai: aiOf(`${f}/x`), cluster: folderCluster(`${f}/x`), date: null, degree: 0,
      children: children.get(folderId(f)) ?? 0, topics: [],
    })),
    ...shown.map((id): GlobeNode => {
      const chat = isChatNote(id);
      return {
        id, kind: chat ? "chat" : "note", title: cleanTitle(labels.get(id), id), path: id,
        depth: id.split("/").length, ai: chat ? aiOf(id) : null, cluster: folderCluster(id),
        date: dateFromName(id), degree: degree.get(id) ?? 0, children: 0,
        topics: (topics.get(id) ?? []).map(baseName),
      };
    }),
  ];

  return {
    nodes,
    links: [...links, ...topicLinks, ...tree],
    counts: {
      chats: nodes.filter((n) => n.kind === "chat").length,
      notes: nodes.filter((n) => n.kind === "note").length,
      folders: folderList.length,
      links: links.length,
    },
    aliases: alias,
  };
}

/** The point that shows a note: a chat's project copy shows as the chat itself. */
export function pointFor(globe: Globe, id: string): string {
  const path = normalize(id);
  return globe.aliases.get(path) ?? path;
}

/* ---------- how a point looks and reads ---------- */

export const GLOBE_COLORS: Readonly<Record<GlobeKind, string>> = {
  chat: "#F2C46D",
  note: "#74C7EF",
  folder: "#F4EFE3",
  core: "#FFFFFF",
};

/** World-space radius: folders grow with what they hold, notes with their links. */
export function radiusOf(n: GlobeNode): number {
  if (n.kind === "core") return 12;
  if (n.kind === "folder") return n.depth >= 2 ? 2.2 : 3.5 + Math.min(5, Math.sqrt(n.children) * 0.5);
  return (n.kind === "chat" ? 3 : 3.6) + Math.min(6, Math.sqrt(n.degree) * 0.6);
}

/**
 * Every folder's floating name. Top-level folders read in capitals ("AI CHATS"),
 * deeper folders in their own case ("Claude", "Coding"); the map shows the deeper
 * ones only as the camera comes closer.
 */
export function folderName(n: GlobeNode): string | null {
  if (n.kind === "core") return "YOUR VAULT";
  if (n.kind !== "folder") return null;
  const name = n.title.replace(/^\d+\s+/, "").trim() || n.title;
  return n.depth === 1 ? name.toUpperCase() : name;
}

/* ---------- time: the rings under the map ---------- */

export const DAY_MS = 86_400_000;

/** The labeled age rings; a map shows the ones up to its oldest dated dot. */
export const AGE_RINGS: readonly Readonly<{ days: number; label: string }>[] = [
  { days: 7, label: "1 week" },
  { days: 30, label: "1 month" },
  { days: 91, label: "3 months" },
  { days: 182, label: "6 months" },
  { days: 365, label: "1 year" },
  { days: 730, label: "2 years" },
];

/** Distance from the middle for age 0, and for the outermost ring in use. */
export const TIME_INNER = 90;
export const TIME_OUTER = 700;
/** Notes and chats with no date in their file name sit on this ring, outside the age rings. */
export const NO_DATE_RADIUS = 840;

/** Whole days from a YYYY-MM-DD date to now (0 for today or a future date). */
export function ageDays(date: string, nowMs: number): number {
  const [y, m, d] = date.split("-").map(Number);
  const then = new Date(y, m - 1, d).getTime();
  return Math.max(0, Math.floor((nowMs - then) / DAY_MS));
}

export type TimeScale = Readonly<{
  /** Age at the outermost ring in use. */
  maxDays: number;
  rings: readonly Readonly<{ days: number; label: string; radius: number }>[];
}>;

/** Square root, like the old star chart: recent weeks get room, old months share the outside. */
export function ageRadius(days: number, maxDays: number): number {
  return TIME_INNER + (TIME_OUTER - TIME_INNER) * Math.sqrt(Math.min(days, maxDays) / maxDays);
}

/** The rings to draw: every age ring up to the first one that holds the oldest dated dot. */
export function timeScale(dates: readonly string[], nowMs: number): TimeScale {
  const oldest = dates.reduce((max, d) => Math.max(max, ageDays(d, nowMs)), 0);
  const last = AGE_RINGS.find((r) => r.days >= oldest) ?? AGE_RINGS[AGE_RINGS.length - 1];
  const rings = AGE_RINGS.filter((r) => r.days <= last.days);
  return {
    maxDays: last.days,
    rings: rings.map((r) => ({ ...r, radius: ageRadius(r.days, last.days) })),
  };
}

/* ---------- folders: slices of the circle ---------- */

export type Arc = Readonly<{ from: number; to: number }>;
export const arcMiddle = (a: Arc): number => (a.from + a.to) / 2;

/** Every item in a split gets at least this share of its parent's arc, so small folders stay readable. */
const MIN_SHARE = 0.03;
/** Space kept clear at each end of an item's arc, as a share of the item's arc (at most 0.6 degrees). */
const ARC_PAD = 0.08;
const MAX_PAD = 0.01;

type Weighted = Readonly<{ key: string; weight: number }>;

/** Split an arc among items by weight, each at least MIN_SHARE of it, in the given order. */
function splitArc(arc: Arc, items: readonly Weighted[]): Map<string, Arc> {
  const out = new Map<string, Arc>();
  if (!items.length) return out;
  const total = items.reduce((sum, i) => sum + i.weight, 0) || 1;
  const floor = Math.min(MIN_SHARE, 1 / items.length);
  const shares = items.map((i) => Math.max(i.weight / total, floor));
  const scale = shares.reduce((a, b) => a + b, 0);
  const length = arc.to - arc.from;
  let at = arc.from;
  items.forEach((item, i) => {
    const size = (shares[i] / scale) * length;
    const pad = Math.min(MAX_PAD, size * ARC_PAD);
    out.set(item.key, { from: at + pad, to: at + size - pad });
    at += size;
  });
  return out;
}

/** The key for "the dots that sit directly in this folder" when its arc is split (no folder path starts with "/"). */
const OWN = "/own";

/**
 * Give every folder a slice of the circle, sized by how many chats and notes it holds; inside it,
 * each subfolder gets a slice the same way, and the folder's own dots share what is left. Returns
 * the slice of every folder (by path; "" is the vault root) and the slice each dot must stay inside.
 */
export function folderArcs(globe: Globe): Readonly<{ folders: ReadonlyMap<string, Arc>; dots: ReadonlyMap<string, Arc> }> {
  const dotsIn = new Map<string, string[]>();
  const subtree = new Map<string, number>();
  const childFolders = new Map<string, string[]>();
  for (const n of globe.nodes) {
    if (n.kind === "folder") {
      const parent = parentPath(n.path);
      childFolders.set(parent, [...(childFolders.get(parent) ?? []), n.path]);
    } else if (n.kind === "chat" || n.kind === "note") {
      const folder = parentPath(n.path);
      dotsIn.set(folder, [...(dotsIn.get(folder) ?? []), n.id]);
      for (let f: string | null = folder; f !== null; f = f ? parentPath(f) : null) {
        subtree.set(f, (subtree.get(f) ?? 0) + 1);
      }
    }
  }
  const folders = new Map<string, Arc>();
  const dots = new Map<string, Arc>();
  const visit = (folder: string, arc: Arc) => {
    folders.set(folder, arc);
    const own = dotsIn.get(folder) ?? [];
    const children = [...(childFolders.get(folder) ?? [])].sort((a, b) => a.localeCompare(b));
    const items: Weighted[] = [
      ...children.map((c) => ({ key: c, weight: subtree.get(c) ?? 0 })),
      ...(own.length ? [{ key: OWN, weight: own.length }] : []),
    ];
    const split = splitArc(arc, items);
    const ownArc = split.get(OWN);
    if (ownArc) own.forEach((id) => dots.set(id, ownArc));
    children.forEach((c) => {
      const childArc = split.get(c);
      if (childArc) visit(c, childArc);
    });
  };
  visit("", { from: 0, to: Math.PI * 2 });
  return { folders, dots };
}

/** How far from the middle a folder's name sits: outside every ring, top folders outermost. */
export function hubRadius(depth: number): number {
  return NO_DATE_RADIUS + 90 + Math.max(0, 3 - depth) * 55;
}

/** Where a dot sits from the middle: by age when it has a date, on the no-date ring when not, nowhere for folders. */
export function ringRadius(n: GlobeNode, scale: TimeScale, nowMs: number): number | null {
  if (n.kind !== "chat" && n.kind !== "note") return null;
  return n.date ? ageRadius(ageDays(n.date, nowMs), scale.maxDays) : NO_DATE_RADIUS;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-07-04" -> "Jul 4, 2026". */
export function readableDate(date: string): string {
  const [y, m, d] = date.split("-").map(Number);
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

/** One plain line under a point's title: what it is, and when for chats. */
export function describe(n: GlobeNode): string {
  if (n.kind === "core") return "The center of your vault";
  if (n.kind === "folder") return `Folder · ${n.children} ${n.children === 1 ? "item" : "items"}`;
  if (n.kind === "chat") {
    const who = n.ai ? `${n.ai} chat` : "AI chat";
    return n.date ? `${who} · ${readableDate(n.date)}` : who;
  }
  const where = n.cluster === "Vault" ? "Note" : `Note in ${n.cluster}`;
  return n.date ? `${where} · ${readableDate(n.date)}` : where;
}

export type GlobeFilter = Readonly<{ cluster: string; includeChats: boolean }>;

export const SHOW_ALL: GlobeFilter = { cluster: "all", includeChats: true };

/** Folders and the vault always stay; notes and chats follow the Map's filters. */
export function isShown(n: GlobeNode, filter: GlobeFilter): boolean {
  if (n.kind === "core" || n.kind === "folder") return true;
  if (n.kind === "chat" && !filter.includeChats) return false;
  return filter.cluster === "all" || n.cluster === filter.cluster;
}

export function matchesQuery(n: GlobeNode, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return n.title.toLowerCase().includes(q) || n.path.toLowerCase().includes(q);
}

/** The folder names the Map's folder filter offers, in order. */
export function clusterNames(globe: Globe): string[] {
  const names = new Set<string>();
  for (const n of globe.nodes) if (n.kind === "chat" || n.kind === "note") names.add(n.cluster);
  return [...names].sort((a, b) => a.localeCompare(b));
}
