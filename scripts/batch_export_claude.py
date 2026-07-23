"""
batch_export_claude.py — Batch-export Claude Code session transcripts (.jsonl) into
the Obsidian vault as per-session markdown notes, skipping sessions already exported.

Scans every project subdirectory under ~/.claude/projects (Claude Code fans transcripts
out into one folder per project), not just the first one found, so sessions from every
project get picked up.
"""
import os
import json
import datetime

import sb_common


def parse_jsonl(input_path, output_path, title):
    transcript = []
    transcript.append(f"# Chat Transcript: {title}\n")
    transcript.append(f"*Source Log File: [{os.path.basename(input_path)}](file:///{input_path.replace(os.sep, '/')})*\n\n---\n\n")

    last_role = None
    with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            try:
                data = json.loads(line.strip())
            except Exception:
                continue

            if 'type' not in data:
                continue

            # --- User Message ---
            if data.get('type') == 'user' and 'message' in data:
                msg = data['message']
                if msg.get('role') == 'user':
                    content = msg.get('content', '')
                    text_parts = []

                    if isinstance(content, str):
                        text_parts.append(content)
                    elif isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict):
                                if part.get('type') == 'text':
                                    text_parts.append(part.get('text', ''))
                                elif part.get('type') == 'input_text':
                                    text_parts.append(part.get('text', ''))
                                elif part.get('type') == 'image':
                                    text_parts.append("*[Embedded Image]*")

                    full_text = "\n".join(text_parts).strip()
                    if "local-command-caveat" in full_text or "<command-name>" in full_text or "<task-notification>" in full_text:
                        continue

                    if full_text:
                        transcript.append(f"## 👤 User\n\n{full_text}\n\n")
                        last_role = 'user'

            # --- Assistant Message ---
            elif data.get('type') == 'assistant' and 'message' in data:
                msg = data['message']
                if msg.get('role') == 'assistant':
                    content = msg.get('content', [])
                    text_parts = []
                    thinking_parts = []

                    if isinstance(content, str):
                        text_parts.append(content)
                    elif isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict):
                                if part.get('type') == 'text':
                                    text_parts.append(part.get('text', ''))
                                elif part.get('type') == 'thinking':
                                    thinking_parts.append(part.get('thinking', ''))

                    full_text = "\n".join(text_parts).strip()
                    full_thinking = "\n".join(thinking_parts).strip()

                    if full_thinking:
                        transcript.append(f"## 🤖 Claude\n\n<details>\n<summary>💭 View Thinking Process</summary>\n\n{full_thinking}\n\n</details>\n\n")
                        if full_text:
                            transcript.append(f"{full_text}\n\n")
                        last_role = 'assistant'
                    elif full_text:
                        if last_role == 'assistant':
                            transcript.append(f"{full_text}\n\n")
                        else:
                            transcript.append(f"## 🤖 Claude\n\n{full_text}\n\n")
                            last_role = 'assistant'

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as out_f:
        out_f.write("".join(transcript))


def collect_transcripts(base_projects_dir):
    """Collect .jsonl transcripts from every project subdirectory under
    ~/.claude/projects (the original only ever looked at the first one),
    deduplicated by filename uuid, sorted by mtime descending."""
    seen = {}
    for item in os.listdir(base_projects_dir):
        full_item = os.path.join(base_projects_dir, item)
        if not os.path.isdir(full_item):
            continue
        try:
            entries = os.listdir(full_item)
        except OSError:
            continue
        for fname in entries:
            if not fname.endswith('.jsonl'):
                continue
            uid = fname[:-len('.jsonl')]
            if uid in seen:
                continue
            full_path = os.path.join(full_item, fname)
            try:
                mtime = os.path.getmtime(full_path)
            except OSError:
                continue
            seen[uid] = (full_path, fname, mtime)

    return sorted(seen.values(), key=lambda x: x[2], reverse=True)


def main():
    user_profile = os.path.expanduser('~')
    base_projects_dir = os.path.join(user_profile, '.claude', 'projects')

    vault_dir = os.path.join(sb_common.get_ai_chats_dir(), 'Claude')
    index_path = os.path.join(vault_dir, 'Claude Chat Index.md')

    if not os.path.exists(base_projects_dir):
        print("Claude projects directory not found.")
        return

    transcripts = collect_transcripts(base_projects_dir)
    if not transcripts:
        print("Claude projects directory not found.")
        return

    # Existing files in vault (to avoid duplicate exports)
    existing_mds = sb_common.list_existing_exports(vault_dir)

    exported_entries = []

    for full_path, fname, _mtime in transcripts:
        uid = fname[:-len('.jsonl')]
        short_id = uid[:6]

        # Check if already exported
        if any(short_id.lower() in x for x in existing_mds):
            continue

        # Parse timestamp and first prompt
        timestamp_str = None
        first_prompt = None

        try:
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f_in:
                for line in f_in:
                    d = json.loads(line)
                    if not timestamp_str and 'timestamp' in d:
                        timestamp_str = d['timestamp']
                    if not first_prompt and d.get('type') == 'user' and 'message' in d:
                        content = d['message'].get('content', '')
                        if isinstance(content, str):
                            p_text = content
                        else:
                            p_text = '\n'.join([part.get('text', '') for part in content if part.get('type') in ['text', 'input_text']])
                        if p_text and 'local-command' not in p_text and '<command-name>' not in p_text:
                            first_prompt = p_text
        except Exception:
            pass

        if not first_prompt:
            continue  # Skip empty sessions

        # Calculate date
        date_str = "2026-07-14"
        if timestamp_str:
            try:
                # e.g., 2026-07-14T22:27:16.017Z
                dt = datetime.datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                date_str = dt.strftime('%Y-%m-%d')
            except Exception:
                pass

        # Clean title
        raw_title = sb_common.clean_filename(first_prompt)
        file_name = f"{date_str} - {raw_title} - {short_id}.md"

        # Determine category (subfolder)
        category = sb_common.detect_category(first_prompt)

        output_path = os.path.join(vault_dir, category, file_name)

        # Parse and save
        parse_jsonl(full_path, output_path, f"{raw_title} ({short_id})")
        print(f"Exported: {file_name} -> {category}")

        # Record for index
        # Format link: [[05 AI Chats/Claude/Coding/2026-07-14 - ...|Short Title]]
        rel_link = f"05 AI Chats/Claude/{category}/{os.path.splitext(file_name)[0]}"
        project_link = sb_common.detect_project_link(first_prompt)

        exported_entries.append({
            "date": date_str,
            "link": rel_link,
            "title": raw_title,
            "category": category.lower(),
            "project": project_link
        })

    # Append to index Review Queue if any were exported
    if exported_entries:
        if sb_common.append_index_rows(index_path, exported_entries):
            print(f"Appended {len(exported_entries)} entries to Claude Chat Index.md")
        else:
            print("Warning: could not append entries to Claude Chat Index.md")


if __name__ == '__main__':
    main()
