"""
vault_health_checker.py — Scans the whole Obsidian vault for link/tag hygiene issues.
Reports broken wikilinks, orphaned notes, and notes missing tags (with suggestions),
writing the result to 00 Home/Vault Health Report.md.
"""
import os
import re
import datetime

import sb_common

def parse_links(content):
    # Matches [[Note Name]] or [[Note Name|Alias]]
    # Exclude external links, images, or tags
    links = re.findall(r'\[\[([^\]\|]+)(?:\|[^\]]+)?\]\]', content)
    return [link.strip() for link in links if not link.startswith('http') and not link.startswith('file:')]

def parse_tags(content):
    # Matches tags like #tag-name or yaml frontmatter tags
    # Let's extract tags from the text body using regex
    body_tags = re.findall(r'(?<!\S)#([a-zA-Z_][a-zA-Z0-9_\-/]*)', content)

    # Matches tags inside YAML frontmatter
    yaml_tags = []
    frontmatter_match = re.match(r'^---\r?\n(.*?)\r?\n---', content, re.DOTALL)
    if frontmatter_match:
        yaml_content = frontmatter_match.group(1)
        # matches: tags: [a, b, c] or tags: \n  - a\n  - b
        tags_line = re.search(r'^tags:\s*\[(.*?)\]', yaml_content, re.MULTILINE)
        if tags_line:
            yaml_tags.extend([t.strip().strip('"').strip("'") for t in tags_line.group(1).split(',') if t.strip()])
        else:
            # check multiline list
            multiline_tags = re.findall(r'^\s*-\s*([^\s#]+)', yaml_content, re.MULTILINE)
            if multiline_tags:
                yaml_tags.extend(multiline_tags)

    return list(set(body_tags + yaml_tags))

def suggest_tags(title, content):
    content_lower = content.lower() + " " + title.lower()
    suggestions = []

    # Keyword rules
    rules = {
        "#school": ["essay", "thesis", "assignment", "homework", "math", "class", "course", "lecture", "study", "university", "college", "professor"],
        "#coding": ["react", "python", "javascript", "code", "git", "api", "database", "sql", "function", "development", "bug", "node", "npm", "script"],
        "#personal": ["subscription", "charge", "bank", "purchase", "progressive", "weed", "tiktok", "personal", "finance", "bill", "receipt"],
        "#second-brain": ["obsidian", "second brain", "rag", "embedding", "vector", "retrieve", "prompt", "chat", "archive"]
    }

    for tag, keywords in rules.items():
        if any(kw in content_lower for kw in keywords):
            suggestions.append(tag)

    return suggestions

def main():
    vault_dir = sb_common.get_vault_path()
    report_path = os.path.join(vault_dir, '00 Home', 'Vault Health Report.md')

    # Exclude directories
    exclude_dirs = {'.obsidian', '.smart-env', 'Templates', '99 Archive', 'Obsidian Vault Backup', '99 Import Logs'}

    all_notes = {}  # Normalized Title -> Relative Path
    note_details = {}  # Relative Path -> {title, content, links, tags}

    # 1. First pass: scan all notes
    for root, dirs, files in os.walk(vault_dir):
        dirs[:] = [d for d in dirs if d not in exclude_dirs and not d.startswith('.')]

        for f in files:
            if not f.endswith('.md'):
                continue

            # Never analyze our own generated report: its tables escape pipes
            # as [[path\|title]], which parses as a link to "path\" (trailing
            # backslash, never resolvable) — so every row of the previous
            # report counted as a broken link and the count compounded each run.
            if f == 'Vault Health Report.md':
                continue

            filepath = os.path.join(root, f)
            rel_path = os.path.relpath(filepath, vault_dir)
            title = f.replace('.md', '')

            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as file_in:
                    content = file_in.read()

                links = parse_links(content)
                tags = parse_tags(content)

                note_details[rel_path] = {
                    "title": title,
                    "content": content,
                    "links": links,
                    "tags": tags
                }

                # Register all possible ways to reference this note in Obsidian
                # Obsidian links can be:
                # 1. Exact filename: [[Note Name]]
                # 2. Subfolder path: [[Folder/Note Name]]
                # 3. Complete relative path: [[03 School/Folder/Note Name]]
                all_notes[title.lower()] = rel_path
                all_notes[rel_path.replace('.md', '').lower()] = rel_path
                all_notes[rel_path.lower()] = rel_path
            except Exception as e:
                print(f"Error reading {filepath}: {e}")

    # 2. Second pass: link and tag analysis
    broken_links = []  # List of {source_note, target_link}
    incoming_links = {rel: [] for rel in note_details.keys()}  # target -> [sources]
    tagless_notes = []

    def is_chat_note(rel_path: str) -> bool:
        # Archived chat transcripts quote wikilink syntax verbatim and have
        # no curated tags, so counting them floods the report with noise.
        # They stay registered as link *targets* and their real links still
        # rescue other notes from orphandom; they just aren't reported on.
        return rel_path.replace('\\', '/').startswith('05 AI Chats/')

    for rel_path, details in note_details.items():
        for link in details['links']:
            normalized_link = link.lower()
            # Clean anchors (e.g. [[Note Name#Section]] -> [[Note Name]])
            if '#' in normalized_link:
                normalized_link = normalized_link.split('#')[0]

            if normalized_link in all_notes:
                target_rel = all_notes[normalized_link]
                incoming_links[target_rel].append(rel_path)
            else:
                # Exclude internal headers references within the same file (e.g. [[#Section]])
                # and unresolved links merely quoted inside chat transcripts.
                if not link.startswith('#') and not is_chat_note(rel_path):
                    broken_links.append({
                        "source": rel_path,
                        "link": link
                    })

        # Check for empty/missing tags (chat exports are expected to be tagless)
        if not details['tags'] and not is_chat_note(rel_path):
            suggestions = suggest_tags(details['title'], details['content'])
            tagless_notes.append({
                "note": rel_path,
                "title": details['title'],
                "suggestions": suggestions
            })

    # Find orphaned notes (0 incoming links)
    orphaned_notes = []
    for rel_path, incoming in incoming_links.items():
        # Exclude dashboard/home files from being orphans (since they are landing
        # pages) and chat transcripts (only ever reached via their index).
        if len(incoming) == 0 and "Home" not in rel_path and "Index.md" not in rel_path \
                and not is_chat_note(rel_path):
            orphaned_notes.append({
                "note": rel_path,
                "title": note_details[rel_path]['title']
            })

    # 3. Generate Health Report
    total_notes = len(note_details)
    total_links = sum(len(d['links']) for d in note_details.values())
    avg_links = total_links / total_notes if total_notes > 0 else 0

    report = []
    report.append(f"""# Obsidian Vault Health Report

Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## 📊 Quick Stats

- **Total Notes**: {total_notes}
- **Total Internal Links**: {total_links}
- **Average Links per Note**: {avg_links:.2f}
- **Broken Links**: {len(broken_links)}
- **Orphaned Notes**: {len(orphaned_notes)}
- **Notes Lacking Tags**: {len(tagless_notes)}

*Broken-link, orphan, and tag checks skip `05 AI Chats` transcripts (archived chats quote link syntax verbatim and carry no curated tags).*

---

## ❌ Broken Links

These are wikilinks pointing to notes that do not exist:

""")

    if broken_links:
        report.append("| Source Note | Broken Target Link |\n|---|---|\n")
        for bl in broken_links:
            report.append(f"| [[{bl['source']}\\|{note_details[bl['source']]['title']}]] | `{bl['link']}` |\n")
    else:
        report.append("*No broken links found! 🎉*\n")

    report.append("""
---

## 🕸️ Orphaned Notes

These notes exist but have no incoming links from other files in the vault:

""")

    if orphaned_notes:
        for orphan in sorted(orphaned_notes, key=lambda x: x['title']):
            report.append(f"- [[{orphan['note']}|{orphan['title']}]] (`{orphan['note']}`)\n")
    else:
        report.append("*No orphaned notes found! 🎉*\n")

    report.append("""
---

## 🏷️ Missing Tags & Suggestions

These notes do not have any tags. Here are automatically suggested tags based on their content:

""")

    if tagless_notes:
        report.append("| Note | Suggested Tags |\n|---|---|\n")
        for tn in tagless_notes:
            sugg_str = ", ".join(tn['suggestions']) if tn['suggestions'] else "*No suggestions*"
            report.append(f"| [[{tn['note']}\\|{tn['title']}]] | {sugg_str} |\n")
    else:
        report.append("*All notes have tags! 🎉*\n")

    # Write report
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, 'w', encoding='utf-8') as out_f:
        out_f.write("".join(report))

    print(f"Vault Health Report generated successfully: {report_path}")
    print(f"- Found {len(broken_links)} broken links.")
    print(f"- Found {len(orphaned_notes)} orphaned notes.")
    print(f"- Found {len(tagless_notes)} notes without tags.")

if __name__ == '__main__':
    main()
