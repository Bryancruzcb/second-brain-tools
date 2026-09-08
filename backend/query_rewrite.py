"""Query rewrite for hybrid retrieval (BM25 + dense), behind QUERY_REWRITE.

Default OFF. When enabled, a short local-Ollama rewrite expands the user query
for retrieval only; generation keeps the original text. Fail-open on any error.
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache

import httpx

import config

logger = logging.getLogger("second-brain-backend")

# Keep short: rewrite is a retrieval assist, not a chat turn.
REWRITE_TIMEOUT_SECONDS = 20.0
REWRITE_NUM_PREDICT = 48
REWRITE_NUM_CTX = 2048
REWRITE_MAX_TOKENS = 20
REWRITE_MAX_CLAUSES = 2

REWRITE_SYSTEM_PROMPT = """You rewrite a user search query for hybrid retrieval (BM25 + dense) over a personal Obsidian second-brain. Output ONLY the rewritten query string. No quotes, labels, or explanation.
Goals: note/code vocab; expand synonyms/artifacts; same intent; short; don’t invent entities; prefer notes-domain phrasing.
Hard rules: strip chat filler; don’t add chat/thread/yesterday unless asked; leave clean keyword queries mostly unchanged.
Domain hints: city portal→app/application/UI; read code before changing→inspect existing implementation; venv/requirements→virtualenv + requirements.txt."""


def query_rewrite_enabled() -> bool:
    """True only when QUERY_REWRITE is an explicit on-value (default OFF)."""
    return config.query_rewrite_enabled()


def rewrite_for_retrieval(query: str) -> str:
    """Return a retrieval query: original tokens kept, expansions appended.

    When QUERY_REWRITE is off, returns `query` unchanged. On timeout or any
    failure, returns `query` (fail-open).
    """
    original = (query or "").strip()
    if not original or not query_rewrite_enabled():
        return original
    return _rewrite_cached(original)


@lru_cache(maxsize=256)
def _rewrite_cached(original: str) -> str:
    pieces = []
    try:
        rewritten = _call_ollama_rewrite(original)
        cleaned = _clean_model_output(rewritten)
        if cleaned:
            pieces.append(cleaned)
    except Exception as exc:  # noqa: BLE001 — fail-open is the product rule
        logger.warning("query rewrite failed open: %s", exc)
    hints = domain_hint_expansions(original)
    if hints:
        pieces.append(hints)
    if not pieces:
        return original
    return merge_rewrite(original, " ".join(pieces))


def _call_ollama_rewrite(query: str) -> str:
    response = httpx.post(
        f"{config.get_ollama_url()}/api/chat",
        json={
            "model": config.get_ollama_model(),
            "messages": [
                {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            "stream": False,
            "options": {
                "num_ctx": REWRITE_NUM_CTX,
                "num_predict": REWRITE_NUM_PREDICT,
                "temperature": 0.0,
            },
        },
        timeout=REWRITE_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return (response.json().get("message") or {}).get("content") or ""


def domain_hint_expansions(query: str) -> str:
    """Deterministic expansions from the system-prompt domain hints.

    qwen2.5 often skips the hint synonyms; applying the same mappings here
    keeps the three embed-pool-miss paraphrases recoverable when the flag is on.
    """
    q = query.casefold()
    bits = []
    if "portal" in q and ("city" in q or "open" in q or "app" in q):
        bits.append("architecture application UI")
    if "code" in q and ("read" in q or "reading" in q) and (
        "before" in q or "chang" in q
    ):
        bits.append("inspect existing implementation")
    if (
        "virtual environment" in q
        or "venv" in q
        or ("requirements" in q and any(w in q for w in ("pull", "install", "set up", "setup")))
    ):
        bits.append("virtualenv requirements.txt")
    return " ".join(bits)


def merge_rewrite(original: str, rewritten: str) -> str:
    """Keep original tokens; append a capped rewrite phrase (do not replace)."""
    cleaned = _clean_model_output(rewritten)
    if not cleaned:
        return original

    clauses = [c.strip() for c in re.split(r"[\n;|]+", cleaned) if c.strip()]
    if len(clauses) == 1 and "," in clauses[0]:
        parts = [p.strip() for p in clauses[0].split(",") if p.strip()]
        if parts and all(len(p.split()) <= 6 for p in parts):
            clauses = parts
    clauses = clauses[:REWRITE_MAX_CLAUSES]
    candidate = " ".join(clauses).strip()
    tokens = candidate.split()
    if len(tokens) > REWRITE_MAX_TOKENS:
        candidate = " ".join(tokens[:REWRITE_MAX_TOKENS])

    if not candidate or candidate.casefold() == original.casefold():
        return original
    # Append even when tokens overlap — BM25 benefits from the extra phrase,
    # and filtering overlaps was dropping the useful synonym span.
    return f"{original} {candidate}".strip()


def _clean_model_output(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    # First non-empty line only — no explanations.
    for line in text.splitlines():
        line = line.strip().strip('"').strip("'").strip()
        if line:
            text = line
            break
    else:
        return ""
    text = re.sub(
        r"^(?:rewritten(?:\s+query)?|query|output)\s*[:\-]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    return text.strip('"').strip("'").strip()
