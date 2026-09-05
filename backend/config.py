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
    return _positive_int_env("OLLAMA_NUM_CTX", 8192)


def _positive_int_env(name: str, default: int) -> int:
    """Parse an env var as a positive int; anything else yields the default."""
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        return default
    return value if value > 0 else default


def get_top_k() -> int:
    """Chunks handed to the answer model per query (TOP_K to override).

    Measured 2026-09-04 on the 40-case eval at fusion depth 30: hit-rate
    80.0% at k=4, 82.5% at k=6, 85.0% at k=8. Six is the default because
    six chunks (about 3,800 tokens) plus a full conversation history still
    fit the 8,192-token OLLAMA_NUM_CTX default; eight (about 5,100 tokens)
    needs OLLAMA_NUM_CTX=16384.
    """
    return _positive_int_env("TOP_K", 6)


def get_max_chunks_per_note() -> int:
    """Chunks one note may occupy in the served list (MAX_CHUNKS_PER_NOTE).

    Long generic notes place several chunks in the reranked top-k, so raising
    TOP_K alone showed Qwen more of the same notes: measured 2026-09-04 at
    depth 30, the served hit-rate stayed 80.0% from k=4 to k=10 with no cap.
    With one chunk per note the served list matches the note-level view:
    80.0% at k=4, 82.5% at 6, 85.0% at 8. 0 disables the cap; anything
    unparsable falls back to 1.
    """
    raw = os.environ.get("MAX_CHUNKS_PER_NOTE")
    if raw is None:
        return 1
    try:
        value = int(raw)
    except ValueError:
        return 1
    return value if value >= 0 else 1


def get_hybrid_depth() -> int:
    """Candidates fetched per retrieval leg before fusion (HYBRID_DEPTH).

    Pool recall on the eval set: 87.5% at 20, 90.0% at 30, 92.5% at 40,
    95.0% at 80. Delivered hit-rate stops moving past 30 while the
    reranker's cost keeps growing with the pool, so 30 is the knee.
    """
    return _positive_int_env("HYBRID_DEPTH", 30)


def get_rerank_depth() -> int:
    """Size of the fused pool the cross-encoder scores (RERANK_DEPTH).

    Kept equal to HYBRID_DEPTH: the measured configuration fuses two
    30-deep legs and reranks the top 30 of that union.
    """
    return _positive_int_env("RERANK_DEPTH", 30)


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


def get_reranker_onnx_file() -> str:
    """ONNX export of RERANKER_MODEL to serve instead of the torch weights.

    Empty (the default) loads RERANKER_MODEL through sentence-transformers.
    Set it to a file inside the model repo, e.g. "onnx/model_quantized.onnx"
    with RERANKER_MODEL=Xenova/ms-marco-MiniLM-L-6-v2, to rerank through
    onnxruntime. Measured 2026-09-04 on the 40-case eval at depth 30: the
    int8 export of the default model hit the same 32 cases at k=4, 6 and 8
    and reranked in 0.9 s median against 1.5 s for the torch model.
    """
    return os.environ.get("RERANKER_ONNX_FILE", "").strip()


def get_embedding_model() -> str:
    """Bi-encoder used to embed chunks and queries (EMBEDDING_MODEL to override).

    Changing this invalidates every stored embedding — run
    scripts/rebuild_rag_index.py --full afterward or retrieval silently
    compares vectors from different spaces.
    """
    return os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")


def get_query_prefix() -> str:
    """Instruction prepended to queries (not documents) at embed time.

    BGE-family embedders are trained with this query-side instruction; the
    eval A/B measured it worth +2.5 points hit-rate over no prefix with
    bge-small-en-v1.5. EMBEDDING_QUERY_PREFIX overrides (set it empty when
    using a model without a query instruction).
    """
    return os.environ.get(
        "EMBEDDING_QUERY_PREFIX",
        "Represent this sentence for searching relevant passages: ",
    )


def reranker_disabled(name: str) -> bool:
    """Shared kill-switch semantics for RERANKER_MODEL values."""
    return name.strip().lower() in ("", "off", "none", "disabled")
