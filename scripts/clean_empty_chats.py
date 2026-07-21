"""
clean_empty_chats.py — Removes empty or header-only chat export files.
Scans the AI chat export folders (Claude, Codex, Gemini, Gemini CLI) and deletes
any markdown file that has no actual conversation content.
"""
import os

import sb_common

def is_empty_or_header_only(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # If the file is completely empty or just whitespace
        if not content.strip():
            return True

        # Split by the first horizontal rule
        parts = content.split('---', 1)
        if len(parts) < 2:
            # If no horizontal rule, check if it has a User header
            return "## 👤 User" not in content

        body = parts[1].strip()
        if not body:
            return True

        if "## 👤 User" not in body:
            return True

        return False
    except Exception as e:
        print(f"Error reading {filepath}: {e}")
        return False

def clean_directory(source_dir):
    if not os.path.exists(source_dir):
        return 0

    categories = ["Coding", "School", "Personal", "General"]
    deleted_count = 0

    for cat in categories:
        cat_dir = os.path.join(source_dir, cat)
        if not os.path.exists(cat_dir):
            continue

        for f in os.listdir(cat_dir):
            if not f.endswith('.md'):
                continue

            fp = os.path.join(cat_dir, f)
            if is_empty_or_header_only(fp):
                try:
                    os.remove(fp)
                    print(f"Deleted empty/header-only chat: {os.path.join(cat, f)}")
                    deleted_count += 1
                except Exception as e:
                    print(f"Failed to delete {fp}: {e}")

    return deleted_count

def main():
    vault_base = sb_common.get_ai_chats_dir()

    folders = ["Claude", "Codex", "Gemini", "Gemini CLI"]

    total_deleted = 0
    for folder in folders:
        source_dir = os.path.join(vault_base, folder)
        print(f"Scanning folder: {folder}...")
        deleted = clean_directory(source_dir)
        total_deleted += deleted

    print(f"Cleanup finished. Total deleted empty/header-only files: {total_deleted}")

if __name__ == '__main__':
    main()
