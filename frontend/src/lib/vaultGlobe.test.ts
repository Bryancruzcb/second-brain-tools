import { describe, expect, test } from "bun:test";
import {
  CORE_ID,
  SHOW_ALL,
  buildGlobe,
  cleanTitle,
  clusterNames,
  dateFromName,
  describe as describePoint,
  folderId,
  hubLabel,
  isShown,
  matchesQuery,
  pointFor,
  readableDate,
  type GraphInputEdge,
  type GraphInputNode,
} from "./vaultGlobe";

const CHAT = "05 AI Chats/Claude/Coding/2026-07-14 - fix the build - 019ec7.md";
const CHAT_COPY = "02 Projects/Study OS/AI Chat Links/2026-07-14 - fix the build - 019ec7.md";
const CHAT_COPY_2 = "02 Projects/Chat Inbox/AI Chat Links/2026-07-14 - fix the build - 019ec7.md";
const LONE_COPY = "02 Projects/Study OS/AI Chat Links/2026-01-01 - no such chat - abcdef.md";

const NODES: GraphInputNode[] = [
  { id: "00 Home/Home.md", label: "Home" },
  { id: "02 Projects/Study OS/Study OS.md", label: "Study OS" },
  { id: "03 School/CS 149.md", label: "CS 149" },
  { id: CHAT, label: "2026-07-14 - fix the build - 019ec7" },
  { id: CHAT_COPY, label: "2026-07-14 - fix the build - 019ec7" },
  { id: CHAT_COPY_2, label: "2026-07-14 - fix the build - 019ec7" },
  { id: LONE_COPY, label: "2026-01-01 - no such chat - abcdef" },
  { id: "05 AI Chats/Codex/General/2026-08-02 - review my resume - 01a06f.md", label: "2026-08-02 - review my resume - 01a06f" },
  { id: "YOO.md", label: "YOO" },
];

const EDGES: GraphInputEdge[] = [
  { source: "00 Home/Home.md", target: "02 Projects/Study OS/Study OS.md" },
  { source: "02 Projects/Study OS/Study OS.md", target: "00 Home/Home.md" },
  { source: "02 Projects/Study OS/Study OS.md", target: CHAT_COPY },
  { source: "03 School/CS 149.md", target: "00 Home/Home.md", is_ghost: true },
  { source: CHAT, target: CHAT_COPY },
];

const globe = buildGlobe(NODES, EDGES);
const byId = new Map(globe.nodes.map((n) => [n.id, n]));
const linksOf = (kind: string) => globe.links.filter((l) => l.kind === kind);

describe("buildGlobe", () => {
  test("folds a chat's project copies into the chat and files it under each project", () => {
    expect(byId.has(CHAT_COPY)).toBe(false);
    expect(byId.has(CHAT_COPY_2)).toBe(false);
    expect(byId.get(CHAT)?.topics).toEqual(["Study OS", "Chat Inbox"]);
    expect(linksOf("topic")).toEqual([
      { source: CHAT, target: folderId("02 Projects/Study OS"), kind: "topic" },
      { source: CHAT, target: folderId("02 Projects/Chat Inbox"), kind: "topic" },
    ]);
    expect(pointFor(globe, CHAT_COPY)).toBe(CHAT);
    expect(pointFor(globe, "00 Home/Home.md")).toBe("00 Home/Home.md");
  });

  test("keeps a copy whose chat is not in the vault as an ordinary note", () => {
    expect(byId.get(LONE_COPY)?.kind).toBe("note");
    expect(pointFor(globe, LONE_COPY)).toBe(LONE_COPY);
  });

  test("draws each real link once, redirects links to a copy, and skips ghost and self links", () => {
    const pairs = linksOf("link").map((l) => [l.source, l.target]);
    expect(pairs).toEqual([
      ["00 Home/Home.md", "02 Projects/Study OS/Study OS.md"],
      ["02 Projects/Study OS/Study OS.md", CHAT],
    ]);
    expect(byId.get("02 Projects/Study OS/Study OS.md")?.degree).toBe(2);
    expect(byId.get("03 School/CS 149.md")?.degree).toBe(0);
    expect(globe.counts.links).toBe(2);
  });

  test("hangs every point on its folder, every folder on its parent, and top level on the vault", () => {
    const parent = new Map(linksOf("tree").map((l) => [l.source, l.target]));
    expect(parent.get(CHAT)).toBe(folderId("05 AI Chats/Claude/Coding"));
    expect(parent.get(folderId("05 AI Chats/Claude/Coding"))).toBe(folderId("05 AI Chats/Claude"));
    expect(parent.get(folderId("05 AI Chats"))).toBe(CORE_ID);
    expect(parent.get("YOO.md")).toBe(CORE_ID);
    // The Chat Inbox folder exists only through a folded copy, and still gets a point.
    expect(byId.get(folderId("02 Projects/Chat Inbox"))?.kind).toBe("folder");
    expect(byId.get(folderId("02 Projects"))?.children).toBe(2);
    expect(byId.get(CORE_ID)?.children).toBe(5);
  });

  test("counts chats, notes, and folders", () => {
    // 11 folders: the lone copy keeps "Study OS/AI Chat Links" alive.
    expect(globe.counts).toEqual({ chats: 2, notes: 5, folders: 11, links: 2 });
  });

  test("reads the chat's AI, date, and a clean title from its path", () => {
    const chat = byId.get(CHAT);
    expect(chat?.kind).toBe("chat");
    expect(chat?.ai).toBe("Claude");
    expect(chat?.date).toBe("2026-07-14");
    expect(chat?.title).toBe("fix the build");
    expect(chat?.cluster).toBe("Chats");
    expect(byId.get(folderId("05 AI Chats/Claude"))?.ai).toBe("Claude");
    expect(byId.get(folderId("05 AI Chats"))?.ai).toBeNull();
  });

  test("accepts Windows separators and duplicate nodes", () => {
    const g = buildGlobe(
      [{ id: "03 School\\CS 149.md", label: "CS 149" }, { id: "03 School/CS 149.md", label: "again" }],
      [],
    );
    expect(g.nodes.filter((n) => n.kind === "note").map((n) => [n.id, n.title])).toEqual([["03 School/CS 149.md", "CS 149"]]);
  });

  test("an empty graph is just the vault", () => {
    const g = buildGlobe([], []);
    expect(g.nodes.map((n) => n.id)).toEqual([CORE_ID]);
    expect(g.links).toEqual([]);
  });
});

describe("labels and words", () => {
  test("cleanTitle drops the date prefix and session id but keeps ordinary titles", () => {
    expect(cleanTitle("2026-09-12 - model model - 01a094760913", "x.md")).toBe("model model");
    expect(cleanTitle("Daily Chat Archive - Bryans-iMac.local", "x.md")).toBe("Daily Chat Archive - Bryans-iMac.local");
    expect(cleanTitle(undefined, "03 School/CS 149.md")).toBe("CS 149");
    expect(cleanTitle("2026-01-01 - abcdef", "x.md")).toBe("abcdef");
  });

  test("dateFromName only reads a date at the start of the file name", () => {
    expect(dateFromName("05 AI Chats/2026-07-14 - x.md")).toBe("2026-07-14");
    expect(dateFromName("2026-07-14 notes/x.md")).toBeNull();
  });

  test("hub labels name the top folders, each AI's folder, and the vault", () => {
    expect(hubLabel(byId.get(CORE_ID)!)).toBe("YOUR VAULT");
    expect(hubLabel(byId.get(folderId("02 Projects"))!)).toBe("PROJECTS");
    expect(hubLabel(byId.get(folderId("05 AI Chats/Claude"))!)).toBe("CLAUDE");
    expect(hubLabel(byId.get(folderId("05 AI Chats/Claude/Coding"))!)).toBeNull();
    expect(hubLabel(byId.get(folderId("02 Projects/Study OS"))!)).toBeNull();
    expect(hubLabel(byId.get(CHAT)!)).toBeNull();
  });

  test("describe says what a point is in plain words", () => {
    expect(describePoint(byId.get(CHAT)!)).toBe("Claude chat · Jul 14, 2026");
    expect(describePoint(byId.get("02 Projects/Study OS/Study OS.md")!)).toBe("Note in Projects");
    expect(describePoint(byId.get("YOO.md")!)).toBe("Note");
    expect(describePoint(byId.get(folderId("02 Projects"))!)).toBe("Folder · 2 items");
    expect(readableDate("2026-01-05")).toBe("Jan 5, 2026");
  });
});

describe("filters", () => {
  test("the Map's folder and chat filters hide notes but never folders", () => {
    const chat = byId.get(CHAT)!;
    const note = byId.get("03 School/CS 149.md")!;
    const folder = byId.get(folderId("03 School"))!;
    expect(isShown(chat, SHOW_ALL)).toBe(true);
    expect(isShown(chat, { cluster: "all", includeChats: false })).toBe(false);
    expect(isShown(note, { cluster: "Projects", includeChats: true })).toBe(false);
    expect(isShown(note, { cluster: "School", includeChats: true })).toBe(true);
    expect(isShown(folder, { cluster: "Projects", includeChats: false })).toBe(true);
  });

  test("matchesQuery looks at the title and the path, ignoring case", () => {
    const chat = byId.get(CHAT)!;
    expect(matchesQuery(chat, "")).toBe(true);
    expect(matchesQuery(chat, "BUILD")).toBe(true);
    expect(matchesQuery(chat, "coding")).toBe(true);
    expect(matchesQuery(chat, "resume")).toBe(false);
  });

  test("clusterNames lists the folders that hold notes or chats", () => {
    expect(clusterNames(globe)).toEqual(["Chats", "Home", "Projects", "School", "Vault"]);
  });
});
