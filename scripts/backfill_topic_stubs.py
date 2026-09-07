"""
backfill_topic_stubs.py — create topic link stubs for existing AI chat transcripts.

Walks 05 AI Chats/, keeps only exporter-written transcripts, matches topic_routes.json,
and writes/updates stubs under topic folders (including Chat Inbox default).
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import sb_common
import topic_router

FNAME_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}) - (?P<title>.+) - (?P<sid>[A-Za-z0-9]{4,12})\.md$",
    re.IGNORECASE,
)


def source_from_rel(rel: str) -> str:
    parts = Path(rel).parts
    if len(parts) >= 2 and parts[0] == "05 AI Chats":
        return parts[1]
    return "Unknown"


def excerpt_from_transcript(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read(8000)
    except OSError:
        return ""
    m = re.search(r"^##\s+.*User\s*\n+(.*?)(?=\n##\s|\Z)", text, re.I | re.S | re.M)
    if m:
        body = re.sub(r"\s+", " ", m.group(1).strip())
        return body[:500]
    lines = []
    for line in text.splitlines():
        if line.startswith("# Chat Transcript") or line.startswith("*Source Log File"):
            continue
        if line.strip() == "---":
            continue
        if line.startswith("##"):
            break
        if line.strip():
            lines.append(line.strip())
        if sum(len(x) for x in lines) > 400:
            break
    return " ".join(lines)[:500]


def main() -> int:
    vault = sb_common.get_vault_path()
    ai_root = sb_common.get_ai_chats_dir()
    if not os.path.isdir(ai_root):
        print(f"AI chats dir missing: {ai_root}")
        return 1

    scanned = 0
    transcripts = 0
    matched = 0
    written = 0
    skipped_non_export = 0
    by_topic: dict[str, int] = {}

    for root, _dirs, files in os.walk(ai_root):
        for name in files:
            if not name.endswith(".md"):
                continue
            lower = name.lower()
            if lower.endswith("chat index.md") or lower == "index.md":
                continue
            scanned += 1
            path = os.path.join(root, name)
            if not sb_common.is_generated_transcript(path):
                skipped_non_export += 1
                continue
            transcripts += 1

            m = FNAME_RE.match(name)
            if m:
                date_str = m.group("date")
                title = m.group("title")
                short_id = m.group("sid")
            else:
                date_str = "1970-01-01"
                title = os.path.splitext(name)[0]
                short_id = "backfill"

            rel = os.path.relpath(path, vault)
            source = source_from_rel(rel)
            excerpt = excerpt_from_transcript(path) or title
            parts = Path(rel).parts
            # 05 AI Chats / <Source> / <Category> / file.md
            category_hint = parts[2] if len(parts) >= 4 else None
            text_for_match = f"{title}\n{excerpt}\n{category_hint or ''}"

            keyword_route = topic_router.match_route(text_for_match)
            if keyword_route:
                matched += 1

            result = topic_router.route_chat(
                source=source,
                title=title,
                date_str=date_str,
                short_id=short_id,
                first_prompt=excerpt,
                transcript_path=path,
                category=category_hint,
            )
            if result:
                written += 1
                tid = (result.get("route") or {}).get("id", "?")
                by_topic[tid] = by_topic.get(tid, 0) + 1

    print("=== topic stub backfill ===")
    print(f"scanned md files:     {scanned}")
    print(f"exporter transcripts: {transcripts}")
    print(f"skipped hand-written: {skipped_non_export}")
    print(f"keyword topic hits:   {matched}")
    print(f"stubs written:        {written}")
    for tid, n in sorted(by_topic.items(), key=lambda x: (-x[1], x[0])):
        print(f"  {tid}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
