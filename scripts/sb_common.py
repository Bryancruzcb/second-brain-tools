"""
sb_common.py — shared helpers for the chat-archive pipeline scripts.

Every script in this directory resolves the vault the same way:
OBSIDIAN_VAULT_PATH env var first, then the known OneDrive locations.
"""
import os
import re


def get_vault_path() -> str:
    configured = os.environ.get("OBSIDIAN_VAULT_PATH")
    if configured:
        return os.path.abspath(os.path.expanduser(configured))

    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, "OneDrive", "Documents", "Obsidian Vault"),
        os.path.join(home, "Library", "CloudStorage", "OneDrive-Personal", "Documents", "Obsidian Vault"),
        os.path.join(home, "Documents", "Obsidian Vault"),
    ]
    return os.path.abspath(next((p for p in candidates if os.path.isdir(p)), candidates[0]))


def get_ai_chats_dir() -> str:
    return os.path.join(get_vault_path(), "05 AI Chats")


MAX_TITLE_LEN = 60


def clean_filename(text: str, fallback: str = "Untitled Session") -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[^a-zA-Z0-9\s_\-]", "", text)
    title = " ".join(text.split()[:6])
    # A URL or pasted path can survive as one enormous "word" and push the
    # vault file path past Windows' 260-char MAX_PATH, crashing the export.
    title = title[:MAX_TITLE_LEN].rstrip()
    return title or fallback


SCHOOL_KEYWORDS = ["essay", "thesis", "slave trade", "grading", "class", "homework", "math"]
PERSONAL_KEYWORDS = ["subscription", "charge", "refund", "law", "progressive", "weed", "tiktok"]


def detect_category(first_prompt: str) -> str:
    lowered = first_prompt.lower()
    if any(k in lowered for k in SCHOOL_KEYWORDS):
        return "School"
    if any(k in lowered for k in PERSONAL_KEYWORDS):
        return "Personal"
    return "Coding"


def detect_project_link(text: str) -> str:
    lowered = text.lower()
    if "signal-path" in lowered:
        return "[[signal-path]]"
    if "creatorflow" in lowered or "roblox" in lowered:
        return "[[CreatorFlow]]"
    if "quickbite" in lowered:
        return "[[quickbite]]"
    return ""


EXPORT_MARKER = "# Chat Transcript:"


def map_existing_exports(vault_dir: str) -> list[dict]:
    """Every markdown file already in this source's vault tree, with the
    path and mtime needed for staleness checks."""
    existing = []
    if os.path.exists(vault_dir):
        for root, _dirs, files in os.walk(vault_dir):
            for f in files:
                if not f.endswith(".md"):
                    continue
                path = os.path.join(root, f)
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                existing.append({"name": f.lower(), "path": path, "mtime": mtime})
    return existing


def is_generated_transcript(path: str) -> bool:
    """True if the file was written by an exporter (starts with the
    transcript marker). Hand-written session summaries never are, and a
    refresh must never overwrite them."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(len(EXPORT_MARKER) + 8).lstrip().startswith(EXPORT_MARKER)
    except OSError:
        return False


def resolve_export_action(existing: list[dict], short_id: str, source_mtime: float):
    """Decide what to do with a session given what's already in the vault.

    Returns (action, path):
      ("new", None)     — nothing matches this id: export normally
      ("skip", None)    — the vault copy is current, or only hand-written
                          notes exist for this session
      ("refresh", path) — an exporter-written copy exists but the source
                          transcript is newer (the session kept going):
                          rewrite it at its current path, preserving any
                          human rename
    """
    sid = short_id.lower()
    matches = [e for e in existing if sid in e["name"]]
    if not matches:
        return ("new", None)

    generated = [m for m in matches if is_generated_transcript(m["path"])]
    if not generated:
        return ("skip", None)

    target = max(generated, key=lambda m: m["mtime"])
    # 2s slack absorbs filesystem/OneDrive mtime rounding.
    if source_mtime <= target["mtime"] + 2:
        return ("skip", None)
    return ("refresh", target["path"])


INDEX_HEADER = "| Date | Chat | Category | Project |"
INDEX_DIVIDER = "|---|---|---|---|"


def append_index_rows(index_path: str, entries: list[dict]) -> bool:
    """Insert rows right below the Review Queue table header.

    The old version used a regex whose unescaped `|` alternation could match
    the frontmatter `---` fence and then str.replace() rewrote every match in
    the file. This targets the exact header+divider pair and replaces once.
    """
    if not entries or not os.path.exists(index_path):
        return False

    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    rows = "\n".join(
        f"| {e['date']} | [[{e['link']}|{e['title']}]] | {e['category']} | {e['project']} |"
        for e in entries
    )

    for newline in ("\n", "\r\n"):
        anchor = f"{INDEX_HEADER}{newline}{INDEX_DIVIDER}"
        if anchor in content:
            content = content.replace(anchor, f"{anchor}{newline}{rows}", 1)
            with open(index_path, "w", encoding="utf-8") as f:
                f.write(content)
            return True
    return False
