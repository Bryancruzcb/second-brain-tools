"""
rebuild_chat_indices.py — Full regeneration of the per-source Chat Index files.
Rewrites each "<Source> Chat Index.md" from the filesystem contents of its export
folder. This is the self-healing pass that runs after the exporters, so it must
scan every existing export rather than only appending new ones.
"""
import os
import re

import sb_common

def rebuild_index(source_dir, index_path, source_name):
    if not os.path.exists(source_dir):
        print(f"Directory not found: {source_dir}")
        return

    entries = []

    # Categories to scan
    categories = ["Coding", "School", "Personal", "General"]

    for cat in categories:
        cat_dir = os.path.join(source_dir, cat)
        if not os.path.exists(cat_dir):
            continue

        for f in os.listdir(cat_dir):
            if not f.endswith('.md'):
                continue

            fp = os.path.join(cat_dir, f)

            # Extract date and title from filename
            # Naming format: YYYY-MM-DD - [Title] - [Short ID].md
            match = re.match(r'(\d{4}-\d{2}-\d{2}) - (.*) - ([a-f0-9]+)\.md', f)
            if not match:
                continue

            date_str = match.group(1)
            title = match.group(2)
            short_id = match.group(3)

            # Read content to find project links or search keywords
            project_link = ""
            try:
                with open(fp, 'r', encoding='utf-8', errors='ignore') as file_in:
                    content = file_in.read()
                    project_link = sb_common.detect_project_link(content)
            except Exception:
                pass

            # Internal Obsidian link
            # Format: [[05 AI Chats/Source/Category/Filename|Title]]
            rel_path = f"05 AI Chats/{os.path.basename(source_dir)}/{cat}/{f.replace('.md', '')}"
            link_str = f"[[{rel_path}|{title}]]"

            # Get modified/creation time of file to sort accurately
            mtime = os.path.getmtime(fp)

            entries.append({
                "date": date_str,
                "link": link_str,
                "category": cat.lower(),
                "project": project_link,
                "mtime": mtime
            })

    # Sort entries: date descending, then mtime descending
    entries.sort(key=lambda x: (x['date'], x['mtime']), reverse=True)

    # Create the markdown index content
    rows = []
    for entry in entries:
        rows.append(f"| {entry['date']} | {entry['link']} | {entry['category']} | {entry['project']} |")

    table_content = "\n".join(rows)

    # Generate the complete index file content
    index_content = f"""---
type: "chat-index"
source: "{source_name}"
review_status: "unreviewed"
tags:
  - "ai-chat"
  - "{source_name}"
  - "index"
  - "unreviewed"
---
# {source_name.replace('-', ' ').title()} Chat Index

Review status: **unreviewed**
Generated: 2026-07-15T03:28:00.000Z

## Related Hubs

- [[Home]]
- [[Master Context]]
- [[Coding Preferences]]
- [[Commands That Worked]]

## Summary

Index of automatically exported {source_name.replace('-', ' ').title()} chat sessions.

## Review Queue

| Date | Chat | Category | Project |
|---|---|---|---|
{table_content}
"""

    with open(index_path, 'w', encoding='utf-8') as out_f:
        out_f.write(index_content)

    print(f"Rebuilt index {os.path.basename(index_path)} with {len(entries)} entries.")

def main():
    vault_base = sb_common.get_ai_chats_dir()

    sources = [
        ("Claude", "Claude Chat Index.md", "claude"),
        ("Codex", "Codex Chat Index.md", "codex"),
        ("Gemini", "Gemini Chat Index.md", "gemini"),
        ("Gemini CLI", "Gemini CLI Chat Index.md", "gemini-cli")
    ]

    for folder, index_file, name in sources:
        source_dir = os.path.join(vault_base, folder)
        index_path = os.path.join(source_dir, index_file)
        rebuild_index(source_dir, index_path, name)

if __name__ == '__main__':
    main()
