"""Shared configuration resolution for the Second Brain backend.

Centralizes path resolution so main.py, rag_query.py, indexer.py, and
scripts/rebuild_rag_index.py all agree on where the vault and the ChromaDB
store live, instead of each duplicating (and drifting from) its own copy.
"""
import os


def get_vault_path() -> str:
    """Resolve the Obsidian vault consistently across the whole backend.

    Priority:
      1. OBSIDIAN_VAULT_PATH env var, if set.
      2. The first of a few common OneDrive/Documents locations that
         actually exists on disk.
      3. If none exist, the first candidate (so callers get a stable,
         predictable path to report in errors).
    """
    configured_path = os.environ.get("OBSIDIAN_VAULT_PATH")
    if configured_path:
        return os.path.abspath(os.path.expanduser(configured_path))

    home_dir = os.path.expanduser("~")
    candidates = [
        os.path.join(home_dir, "OneDrive/Documents/Obsidian Vault"),
        os.path.join(home_dir, "Library/CloudStorage/OneDrive-Personal/Documents/Obsidian Vault"),
        os.path.join(home_dir, "Documents/Obsidian Vault"),
    ]
    return next((path for path in candidates if os.path.isdir(path)), candidates[0])


def get_chroma_path() -> str:
    """Resolve the ChromaDB persistence directory.

    Priority:
      1. CHROMA_DB_PATH env var, if set.
      2. backend/chroma_db next to this file (this package's own directory),
         which keeps the index colocated with the backend on every machine
         instead of the old hardcoded ~/IdeaProjects/... path.
    """
    configured_path = os.environ.get("CHROMA_DB_PATH")
    if configured_path:
        return os.path.abspath(os.path.expanduser(configured_path))

    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "chroma_db")
