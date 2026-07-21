import os
import json
import re
import datetime

import sb_common

def parse_gemini_jsonl(input_path, output_path, title):
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

            step_type = data.get('type')
            source = data.get('source')
            content = data.get('content', '')

            # --- User Message ---
            if step_type == 'USER_INPUT' or source == 'USER_EXPLICIT':
                # Extract user request from tags if present
                match = re.search(r'<USER_REQUEST>\n?(.*?)\n?</USER_REQUEST>', content, re.DOTALL)
                if match:
                    full_text = match.group(1).strip()
                else:
                    full_text = content.strip()

                if full_text:
                    transcript.append(f"## 👤 User\n\n{full_text}\n\n")
                    last_role = 'user'

            # --- Assistant Message ---
            elif step_type == 'PLANNER_RESPONSE' or source == 'MODEL':
                thinking = data.get('thinking', '').strip()
                full_text = content.strip()

                if thinking:
                    transcript.append(f"## 🤖 Gemini\n\n<details>\n<summary>💭 View Thinking Process</summary>\n\n{thinking}\n\n</details>\n\n")
                    if full_text:
                        transcript.append(f"{full_text}\n\n")
                    last_role = 'assistant'
                elif full_text:
                    if last_role == 'assistant':
                        transcript.append(f"{full_text}\n\n")
                    else:
                        transcript.append(f"## 🤖 Gemini\n\n{full_text}\n\n")
                        last_role = 'assistant'

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as out_f:
        out_f.write("".join(transcript))

def export_sessions(brain_dir, vault_dir, index_path, source_type):
    if not os.path.exists(brain_dir):
        print(f"Brain directory not found: {brain_dir}")
        return

    # Get existing files in vault (to avoid duplicate exports)
    existing_mds = sb_common.list_existing_exports(vault_dir)

    # Find all transcript.jsonl files
    session_dirs = []
    for item in os.listdir(brain_dir):
        full_item = os.path.join(brain_dir, item)
        if os.path.isdir(full_item):
            log_file = os.path.join(full_item, '.system_generated', 'logs', 'transcript.jsonl')
            if os.path.exists(log_file):
                session_dirs.append((item, log_file))

    exported_entries = []

    for uuid, log_file in sorted(session_dirs, key=lambda x: os.path.getmtime(x[1]), reverse=True):
        short_id = uuid[:6]

        # Check if already exported
        if any(short_id.lower() in x for x in existing_mds):
            continue

        # Parse timestamp and first prompt
        timestamp_str = None
        first_prompt = None

        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f_in:
                for line in f_in:
                    d = json.loads(line)
                    if not timestamp_str and 'created_at' in d:
                        timestamp_str = d['created_at']
                    step_type = d.get('type')
                    source = d.get('source')
                    content = d.get('content', '')
                    if not first_prompt and (step_type == 'USER_INPUT' or source == 'USER_EXPLICIT'):
                        match = re.search(r'<USER_REQUEST>\n?(.*?)\n?</USER_REQUEST>', content, re.DOTALL)
                        p_text = match.group(1).strip() if match else content.strip()
                        if p_text:
                            first_prompt = p_text
        except Exception:
            pass

        if not first_prompt:
            continue  # Skip empty sessions

        # Calculate date
        date_str = "2026-07-14"
        if timestamp_str:
            try:
                # e.g., 2026-07-14T22:27:16.017Z or 2026-07-14T22:27:16Z
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
        parse_gemini_jsonl(log_file, output_path, f"{raw_title} ({short_id})")
        print(f"Exported {source_type}: {file_name} -> {category}")

        rel_link = f"05 AI Chats/{'Gemini' if source_type == 'desktop' else 'Gemini CLI'}/{category}/{file_name.replace('.md', '')}"
        project_link = sb_common.detect_project_link(first_prompt)

        exported_entries.append({
            "date": date_str,
            "link": rel_link,
            "title": raw_title,
            "category": category.lower(),
            "project": project_link
        })

    # Append to index Review Queue if any were exported
    if sb_common.append_index_rows(index_path, exported_entries):
        print(f"Appended {len(exported_entries)} entries to index: {os.path.basename(index_path)}")

def main():
    user_profile = os.path.expanduser('~')

    # 1. Desktop Chrome Gemini App Chats
    desktop_brain = os.path.join(user_profile, '.gemini', 'antigravity', 'brain')
    desktop_vault = os.path.join(sb_common.get_ai_chats_dir(), 'Gemini')
    desktop_index = os.path.join(desktop_vault, 'Gemini Chat Index.md')

    os.makedirs(os.path.dirname(desktop_index), exist_ok=True)
    if not os.path.exists(desktop_index):
        initial_desktop_content = """---
type: "chat-index"
source: "gemini"
review_status: "unreviewed"
tags:
  - "ai-chat"
  - "gemini"
  - "index"
  - "unreviewed"
---
# Gemini Chat Index

Review status: **unreviewed**
Generated: 2026-07-15T03:12:00.000Z

## Related Hubs

- [[Home]]
- [[Master Context]]
- [[Coding Preferences]]
- [[Commands That Worked]]

## Summary

Index of automatically exported Gemini chat sessions.

## Review Queue

| Date | Chat | Category | Project |
|---|---|---|---|
"""
        with open(desktop_index, 'w', encoding='utf-8') as f:
            f.write(initial_desktop_content)

    export_sessions(desktop_brain, desktop_vault, desktop_index, "desktop")

    # 2. CLI Gemini App Chats
    cli_brain = os.path.join(user_profile, '.gemini', 'antigravity-cli', 'brain')
    cli_vault = os.path.join(sb_common.get_ai_chats_dir(), 'Gemini CLI')
    cli_index = os.path.join(cli_vault, 'Gemini CLI Chat Index.md')

    # Create the CLI index file if it doesn't exist yet
    os.makedirs(os.path.dirname(cli_index), exist_ok=True)
    if not os.path.exists(cli_index):
        initial_content = """---
type: "chat-index"
source: "gemini-cli"
review_status: "unreviewed"
tags:
  - "ai-chat"
  - "gemini-cli"
  - "index"
  - "unreviewed"
---
# Gemini CLI Chat Index

Review status: **unreviewed**
Generated: 2026-07-15T03:27:00.000Z

## Related Hubs

- [[Home]]
- [[Master Context]]
- [[Coding Preferences]]
- [[Commands That Worked]]

## Summary

Index of automatically exported Gemini CLI chat sessions.

## Review Queue

| Date | Chat | Category | Project |
|---|---|---|---|
"""
        with open(cli_index, 'w', encoding='utf-8') as f:
            f.write(initial_content)

    export_sessions(cli_brain, cli_vault, cli_index, "cli")

if __name__ == '__main__':
    main()
