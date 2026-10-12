import { describe, expect, test } from "bun:test";
import { folderCluster, isChatNote } from "./vaultPaths";

describe("vault paths", () => {
  test("isChatNote finds chats under 05 AI Chats, with either separator", () => {
    expect(isChatNote("05 AI Chats/Claude/x.md")).toBe(true);
    expect(isChatNote("05 AI Chats\\Codex\\x.md")).toBe(true);
    expect(isChatNote("02 Projects/AI Chat Links/x.md")).toBe(false);
  });

  test("folderCluster names the top folder without its number", () => {
    expect(folderCluster("02 Projects/Study OS/x.md")).toBe("Projects");
    expect(folderCluster("05 AI Chats/Claude/x.md")).toBe("Chats");
    expect(folderCluster("YOO.md")).toBe("Vault");
  });
});
