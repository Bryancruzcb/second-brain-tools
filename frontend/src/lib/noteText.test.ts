import { describe, expect, test } from "bun:test";
import { cleanSnippet, noteBlocks } from "./noteText";
import { askedAgo, clockTime, editedPhrase, relativeDay } from "./format";
import { answerFromHistory, uniqueSources } from "./ask";

const COFFEE =
  "# Coffee Brewing\n\nGrind beans fresh each morning, medium coarse for the press.\n\n## Grinder Settings\n\nEighteen clicks on the hand grinder, thirty grams per brew.\n";

describe("cleanSnippet", () => {
  test("drops the title heading and heading marks", () => {
    expect(cleanSnippet(COFFEE, "Coffee Brewing")).toBe(
      "Grind beans fresh each morning, medium coarse for the press. Grinder Settings Eighteen clicks on the hand grinder, thirty grams per brew.",
    );
  });

  test("keeps text when there is no title heading", () => {
    expect(cleanSnippet("Just a line\nand another", "Other")).toBe("Just a line and another");
    expect(cleanSnippet("", "Empty")).toBe("");
  });
});

describe("noteBlocks", () => {
  test("shows the title once and sub-headings as headings", () => {
    expect(noteBlocks(COFFEE, "Coffee Brewing")).toEqual([
      { kind: "paragraph", text: "Grind beans fresh each morning, medium coarse for the press." },
      { kind: "heading", text: "Grinder Settings" },
      { kind: "paragraph", text: "Eighteen clicks on the hand grinder, thirty grams per brew." },
    ]);
  });

  test("keeps line breaks inside a paragraph", () => {
    expect(noteBlocks("# Levain\n\nline one\nline two", "Levain")).toEqual([
      { kind: "paragraph", text: "line one\nline two" },
    ]);
  });

  test("never reads a heading inside a code fence", () => {
    const md = "# T\n\n```sh\n# not a heading\n\necho hi\n```\nafter";
    expect(noteBlocks(md, "T")).toEqual([
      { kind: "code", text: "```sh\n# not a heading\n\necho hi\n```" },
      { kind: "paragraph", text: "after" },
    ]);
  });

  test("keeps a first heading that is not the title", () => {
    expect(noteBlocks("# Something else\nbody", "Title")).toEqual([
      { kind: "heading", text: "Something else" },
      { kind: "paragraph", text: "body" },
    ]);
  });

  test("keeps an unclosed fence as code", () => {
    expect(noteBlocks("```\ncode", "T")).toEqual([{ kind: "code", text: "```\ncode" }]);
  });
});

describe("format", () => {
  const now = Date.parse("2026-10-11T11:40:00-07:00");
  test("relativeDay uses the given now", () => {
    expect(relativeDay("2026-10-11T08:40:00-07:00", now)).toBe("Today");
    expect(relativeDay("2026-10-10T09:05:00-07:00", now)).toBe("Yesterday");
    expect(relativeDay("2026-10-06T07:15:00-07:00", now)).toBe("5d ago");
    expect(relativeDay("2026-09-26T06:50:00-07:00", now)).toBe("Sep 26");
  });

  test("clockTime and askedAgo", () => {
    expect(clockTime("2026-10-11T08:40:00-07:00")).toBe("08:40");
    expect(askedAgo(1791738300, now)).toBe("1h ago");
    expect(askedAgo(now / 1000 - 30, now)).toBe("just now");
  });
});

describe("ask sources", () => {
  test("one source per note, with a clean quote", () => {
    const src = uniqueSources([
      { title: "Sourdough Starter", source: "Sourdough Starter.md", snippet: "# Sourdough Starter\n\nFeed it daily." },
      { title: "Sourdough Starter", source: "Sourdough Starter.md", snippet: "second chunk" },
      { title: "Levain", source: "Levain.md" },
    ]);
    expect(src).toEqual([
      { title: "Sourdough Starter", source: "Sourdough Starter.md", snippet: "Feed it daily." },
      { title: "Levain", source: "Levain.md", snippet: "" },
    ]);
    const a = answerFromHistory({
      id: "x",
      asked_at: 1,
      question: "q",
      answer: "",
      scope: "notes",
      sources: [],
    });
    expect(a.body).toBe("No answer returned.");
    expect(a.historyId).toBe("x");
  });

  test("editedPhrase", () => {
    const now = Date.parse("2026-10-11T11:40:00-07:00");
    expect(editedPhrase("2026-10-11T08:40:00-07:00", now)).toBe("Edited today, 08:40");
    expect(editedPhrase("2026-09-26T06:50:00-07:00", now)).toBe("Edited Sep 26, 06:50");
  });
});
