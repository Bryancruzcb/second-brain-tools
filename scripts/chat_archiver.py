"""
chat_archiver.py — Daily Chat Checker & Archiver
Scans the local AI agent conversation transcripts, consolidates today's chat history,
and exports them as structured markdown notes directly into the Obsidian Vault.
"""
import os
import json
from datetime import datetime, date

def get_today_chats():
    home_dir = os.path.expanduser("~")
    brain_dir = os.path.join(home_dir, ".gemini/antigravity/brain")
    
    if not os.path.exists(brain_dir):
        return []

    today_str = date.today().strftime("%Y-%m-%d")
    today_dialogs = []

    # Traverse all session folders
    for folder in os.listdir(brain_dir):
        logs_path = os.path.join(brain_dir, folder, ".system_generated/logs/transcript.jsonl")
        if not os.path.exists(logs_path):
            continue

        try:
            with open(logs_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            session_messages = []
            for line in lines:
                try:
                    data = json.loads(line)
                    # Check if the step happened today
                    created_at = data.get("created_at", "")
                    if created_at.startswith(today_str):
                        step_type = data.get("type", "")
                        source = data.get("source", "")
                        content = data.get("content", "")
                        
                        if step_type == "USER_INPUT" and source == "USER_EXPLICIT":
                            # Strip USER_REQUEST tags
                            clean_content = content.replace("<USER_REQUEST>", "").replace("</USER_REQUEST>", "").strip()
                            # Clean up additional metadata if present
                            if "<ADDITIONAL_METADATA>" in clean_content:
                                clean_content = clean_content.split("<ADDITIONAL_METADATA>")[0].strip()
                            session_messages.append({"role": "User", "text": clean_content})
                        
                        elif step_type == "PLANNER_RESPONSE" and source == "MODEL":
                            # Use thinking block or general text
                            thinking = data.get("thinking", "").strip()
                            if thinking:
                                session_messages.append({"role": "AI (Thinking)", "text": thinking})
                            
                except Exception:
                    continue
            
            if session_messages:
                today_dialogs.append({
                    "id": folder[:8],
                    "messages": session_messages
                })
        except Exception:
            continue

    return today_dialogs

def main():
    print("🕰️ Running Daily Second Brain Chat Archiver...")
    today_chats = get_today_chats()
    
    if not today_chats:
        print("✓ No chats found for today.")
        return

    today_str = datetime.today().strftime("%Y-%m-%d")
    
    # Target file in local Obsidian Vault
    home_dir = os.path.expanduser("~")
    vault_dir = os.path.join(home_dir, "Library/CloudStorage/OneDrive-Personal/Documents/Obsidian Vault")
    if not os.path.exists(vault_dir):
        vault_dir = os.path.join(home_dir, "OneDrive/Documents/Obsidian Vault")

    gemini_folder = os.path.join(vault_dir, "05 AI Chats/Gemini/Coding")
    os.makedirs(gemini_folder, exist_ok=True)

    filename = f"{today_str} - Daily Chat Archive - Consolidated.md"
    filepath = os.path.join(gemini_folder, filename)

    # Format Markdown
    md_content = []
    md_content.append(f"---")
    md_content.append(f"title: Daily Chat Archive — {today_str}")
    md_content.append(f"date: {today_str}")
    md_content.append(f"tags: [ai-chats, gemini, coding, daily-archive]")
    md_content.append(f"---")
    md_content.append(f"\n# Daily Chat Archive — {today_str}\n")
    md_content.append(f"Consolidated logs of developer chats archived at {datetime.now().strftime('%H:%M:%S')}.\n")

    for session in today_chats:
        md_content.append(f"## Session [{session['id']}]")
        for msg in session["messages"]:
            md_content.append(f"### {msg['role']}")
            md_content.append(f"{msg['text']}\n")
        md_content.append(f"---\n")

    full_md = "\n".join(md_content)

    # Write file
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(full_md)
    print(f"✓ Chat archive saved to: {filepath}")

    # Safely append row to Gemini Chat Index if possible
    index_path = os.path.join(vault_dir, "05 AI Chats/Gemini/Gemini Chat Index.md")
    try:
        new_row = f"| {today_str} | [[05 AI Chats/Gemini/Coding/{today_str} - Daily Chat Archive - Consolidated|Daily Chat Archive — {today_str}]] | Coding | Consolidated |\n"
        with open(index_path, "a", encoding="utf-8") as f:
            f.write(new_row)
        print("✓ Appended link row to Gemini Chat Index.")
    except Exception as e:
        print(f"⚠ Could not write to Chat Index (likely locked/offline): {e}")

if __name__ == "__main__":
    main()
