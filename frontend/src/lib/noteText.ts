/**
 * Calculations over a note's Markdown text: the snippet for a list row, the
 * word count behind a star's size, and the blocks the reading pane renders.
 * All pure: text in, data out.
 */

const HEADING = /^(#{1,6})\s+(.*)$/;
const FENCE = /^\s*(```|~~~)/;

function headingText(line: string): string | null {
  const m = HEADING.exec(line.trim());
  return m ? m[2].trim() : null;
}

/** Non-empty trimmed lines, without the heading line that repeats the title. */
function contentLines(md: string, title: string): string[] {
  return md
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l.length > 0 && headingText(l) !== title.trim());
}

/** One line of plain text for a list row: no "# Title", no heading marks. */
export function cleanSnippet(md: string, title: string): string {
  return contentLines(md, title)
    .map((l) => headingText(l) ?? l)
    .join(" ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Words in the note body, not counting the title heading. */
export function wordCount(md: string, title: string): number {
  const text = cleanSnippet(md, title);
  return text ? text.split(" ").length : 0;
}

export type NoteBlock =
  | { kind: "heading"; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "code"; text: string };

/**
 * Split a note into headings, paragraphs and fenced code for reading. The
 * first heading is dropped when it only repeats the title, so the title shows
 * once. Paragraph text keeps its line breaks and indentation; code fences are
 * kept whole, so a "# comment" inside one is never read as a heading.
 */
export function noteBlocks(md: string, title: string): NoteBlock[] {
  const blocks: NoteBlock[] = [];
  let para: string[] = [];
  let code: string[] | null = null;

  const flushPara = () => {
    if (para.length) blocks.push({ kind: "paragraph", text: para.join("\n") });
    para = [];
  };

  for (const raw of md.replace(/\r\n/g, "\n").split("\n")) {
    if (code) {
      code.push(raw);
      if (FENCE.test(raw) && code.length > 1) {
        blocks.push({ kind: "code", text: code.join("\n") });
        code = null;
      }
      continue;
    }
    if (FENCE.test(raw)) {
      flushPara();
      code = [raw];
      continue;
    }
    if (!raw.trim()) {
      flushPara();
      continue;
    }
    const heading = headingText(raw);
    if (heading !== null) {
      flushPara();
      const repeatsTitle = blocks.length === 0 && heading === title.trim();
      if (!repeatsTitle) blocks.push({ kind: "heading", text: heading });
      continue;
    }
    para.push(raw);
  }
  if (code) blocks.push({ kind: "code", text: code.join("\n") });
  flushPara();
  return blocks;
}
