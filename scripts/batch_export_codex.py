import os
import json
import re
import datetime

import sb_common

def parse_codex_jsonl(input_path, output_path, title):
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

            payload = data.get('payload')
            if not payload or payload.get('type') != 'message':
                continue

            role = payload.get('role')
            content = payload.get('content')
            if not content:
                continue

            text_parts = []
            thinking_parts = []

            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        if part.get('type') == 'text':
                            text_parts.append(part.get('text', ''))
                        elif part.get('type') == 'input_text':
                            text_parts.append(part.get('text', ''))
                        elif part.get('type') == 'thinking':
                            thinking_parts.append(part.get('thinking', ''))

            full_text = "\n".join(text_parts).strip()
            full_thinking = "\n".join(thinking_parts).strip()

            # Skip environment context blocks
            if "environment_context" in full_text or "local-command-caveat" in full_text:
                continue

            if role == 'user':
                if full_text:
                    transcript.append(f"## 👤 User\n\n{full_text}\n\n")
                    last_role = 'user'
            elif role == 'assistant':
                if full_thinking:
                    transcript.append(f"## 🤖 Codex\n\n<details>\n<summary>💭 View Thinking Process</summary>\n\n{full_thinking}\n\n</details>\n\n")
                    if full_text:
                        transcript.append(f"{full_text}\n\n")
                    last_role = 'assistant'
                elif full_text:
                    if last_role == 'assistant':
                        transcript.append(f"{full_text}\n\n")
                    else:
                        transcript.append(f"## 🤖 Codex\n\n{full_text}\n\n")
                        last_role = 'assistant'

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as out_f:
        out_f.write("".join(transcript))

def main():
    user_profile = os.path.expanduser('~')
    sessions_dir = os.path.join(user_profile, '.codex', 'sessions')
    vault_dir = os.path.join(sb_common.get_ai_chats_dir(), 'Codex')
    index_path = os.path.join(vault_dir, 'Codex Chat Index.md')

    if not os.path.exists(sessions_dir):
        print("Codex sessions directory not found.")
        return

    # Get existing files in vault
    existing_mds = sb_common.list_existing_exports(vault_dir)

    # Scan all rollout files recursively under .codex/sessions
    rollout_files = []
    for root, dirs, files in os.walk(sessions_dir):
        for f in files:
            if f.endswith('.jsonl') and f.startswith('rollout-'):
                rollout_files.append(os.path.join(root, f))

    exported_entries = []

    # Sort files by creation time descending
    for fp in sorted(rollout_files, key=lambda x: os.path.getmtime(x), reverse=True):
        f = os.path.basename(fp)

        # Extract ID from filename: rollout-YYYY-MM-DDTHH-MM-SS-[ID].jsonl
        # e.g., rollout-2026-05-02T01-50-21-019de7e1-b236-79f3-8fc8-8e8bf1bf8ebf.jsonl
        match_id = re.search(r'rollout-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-([a-f0-9\-]+)\.jsonl', f)
        if not match_id:
            continue

        full_uuid = match_id.group(1)
        short_id = full_uuid[:6]

        # Check if already exported
        if any(short_id.lower() in x for x in existing_mds):
            continue

        # Parse first user prompt and timestamp
        first_prompt = None
        timestamp_str = None

        try:
            with open(fp, 'r', encoding='utf-8', errors='ignore') as f_in:
                for line in f_in:
                    d = json.loads(line)
                    if not timestamp_str and 'timestamp' in d:
                        timestamp_str = d['timestamp']
                    payload = d.get('payload')
                    if not first_prompt and payload and payload.get('type') == 'message' and payload.get('role') == 'user':
                        content = payload.get('content')
                        if isinstance(content, str):
                            p_text = content
                        else:
                            p_text = '\n'.join([part.get('text', '') for part in content if part.get('type') in ['text', 'input_text']])
                        if p_text and 'environment_context' not in p_text and 'local-command-caveat' not in p_text:
                            first_prompt = p_text
        except Exception:
            pass

        if not first_prompt:
            continue

        # Date
        date_str = "2026-07-14"
        if timestamp_str:
            try:
                dt = datetime.datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                date_str = dt.strftime('%Y-%m-%d')
            except Exception:
                pass

        raw_title = sb_common.clean_filename(first_prompt, "Untitled Codex Session")
        file_name = f"{date_str} - {raw_title} - {short_id}.md"

        # Determine category (subfolder)
        category = sb_common.detect_category(first_prompt)

        output_path = os.path.join(vault_dir, category, file_name)

        parse_codex_jsonl(fp, output_path, f"{raw_title} ({short_id})")
        print(f"Exported Codex: {file_name} -> {category}")

        rel_link = f"05 AI Chats/Codex/{category}/{file_name.replace('.md', '')}"
        project_link = sb_common.detect_project_link(first_prompt)

        exported_entries.append({
            "date": date_str,
            "link": rel_link,
            "title": raw_title,
            "category": category.lower(),
            "project": project_link
        })

    # Append to Codex Chat Index
    if sb_common.append_index_rows(index_path, exported_entries):
        print(f"Appended {len(exported_entries)} entries to Codex Chat Index.md")

if __name__ == '__main__':
    main()
