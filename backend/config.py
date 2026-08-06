"""Shared configuration resolution for the Second Brain backend.

Centralizes configuration so main.py, indexer.py, eval/run_eval.py, and
scripts/rebuild_rag_index.py all agree on paths and model choices, instead
of each duplicating (and drifting from) its own copy.
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
    # abspath normalizes the mixed / and \ separators these literals produce
    # on Windows — resolve_vault_file's commonpath containment check 403s on
    # every note otherwise.
    return os.path.abspath(next((path for path in candidates if os.path.isdir(path)), candidates[0]))


def get_ollama_model() -> str:
    """Ollama model used for chat and co-writing (OLLAMA_MODEL to override)."""
    return os.environ.get("OLLAMA_MODEL", "qwen2.5")


def get_ollama_url() -> str:
    """Base URL of the local Ollama server (OLLAMA_URL to override)."""
    return os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")


def get_ollama_num_ctx() -> int:
    """Context window requested per chat call (OLLAMA_NUM_CTX to override).

    Ollama's own default is small (~4K) and it silently truncates from the
    top when a prompt exceeds it — which would eat the system prompt once
    conversation history is included. 8K fits history + retrieved snippets
    + a 1K answer comfortably on CPU-only hardware.
    """
    try:
        return int(os.environ.get("OLLAMA_NUM_CTX", "8192"))
    except ValueError:
        return 8192


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


def get_reranker_model() -> str:
    """Cross-encoder used to rerank fused retrieval candidates.

    RERANKER_MODEL overrides; set it to "off" to skip reranking and serve
    the fused order directly (useful on very slow CPUs).
    """
    return os.environ.get("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")


def get_embedding_model() -> str:
    """Bi-encoder used to embed chunks and queries (EMBEDDING_MODEL to override).

    Changing this invalidates every stored embedding — run
    scripts/rebuild_rag_index.py --full afterward or retrieval silently
    compares vectors from different spaces.
    """
    return os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")


def get_query_prefix() -> str:
    """Instruction prepended to queries (not documents) at embed time.

    Some embedders (the BGE family) are trained with a query-side
    instruction; EMBEDDING_QUERY_PREFIX overrides, empty by default.
    """
    return os.environ.get("EMBEDDING_QUERY_PREFIX", "")


def reranker_disabled(name: str) -> bool:
    """Shared kill-switch semantics for RERANKER_MODEL values."""
    return name.strip().lower() in ("", "off", "none", "disabled")
