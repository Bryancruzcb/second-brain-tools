"""
topic_embed.py — embedding-based topic scoring + automatic keyword learning.

Uses the same SentenceTransformer model as the backend RAG index
(BAAI/bge-small-en-v1.5 by default). Falls back gracefully if the model
can't load (keyword router + Chat Inbox still work).
"""
from __future__ import annotations

import json
import os
import re
import threading
from typing import Any

ROUTES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "topic_routes.json")
CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".topic_embeddings.json")
LEARN_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "topic_keyword_learning.log")

# Assign when best topic cosine similarity >= this.
ASSIGN_THRESHOLD = float(os.environ.get("TOPIC_EMBED_ASSIGN", "0.50"))
# Only auto-add keywords when the embed (or keyword) assignment is this strong.
LEARN_THRESHOLD = float(os.environ.get("TOPIC_EMBED_LEARN", "0.58"))
MAX_NEW_KEYWORDS_PER_CHAT = 3
MAX_LEARNED_KEYWORDS_PER_TOPIC = 40

_model = None
_model_lock = threading.Lock()
_model_failed = False

STOP = {
    "the", "a", "an", "and", "or", "to", "for", "of", "in", "on", "my", "i", "you",
    "we", "is", "are", "was", "were", "be", "with", "how", "what", "can", "could",
    "would", "should", "this", "that", "it", "me", "im", "so", "uh", "um", "do",
    "does", "did", "from", "as", "at", "about", "into", "over", "under", "your",
    "any", "all", "not", "just", "like", "want", "need", "make", "use", "using",
    "file", "files", "user", "mentioned", "please", "thanks", "hello", "hey",
    "untitled", "session", "chat", "transcript", "effort", "following", "codex",
    "agent", "claude", "gemini", "gpt", "assistant", "true", "false", "null",
}


def _repo_backend() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))


def _load_model():
    global _model, _model_failed
    if _model is not None or _model_failed:
        return _model
    with _model_lock:
        if _model is not None or _model_failed:
            return _model
        try:
            backend = _repo_backend()
            if backend not in os.sys.path:
                os.sys.path.insert(0, backend)
            import config  # type: ignore
            from sentence_transformers import SentenceTransformer  # type: ignore

            name = config.get_embedding_model()
            # HF offline flags already used by auto_archive; allow cache hit.
            _model = SentenceTransformer(name)
            return _model
        except Exception as e:
            _model_failed = True
            print(f"topic_embed: model unavailable ({e}); embedding routing off")
            return None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / ((na ** 0.5) * (nb ** 0.5))


def _topic_profile(route: dict[str, Any]) -> str:
    parts = [
        route.get("title") or "",
        route.get("id") or "",
        route.get("folder") or "",
        route.get("description") or "",
        " ".join(route.get("keywords") or []),
        " ".join(route.get("learned_keywords") or []),
    ]
    return " | ".join(p for p in parts if p)


def _fingerprint(routes: list[dict[str, Any]]) -> str:
    blob = json.dumps(
        [
            {
                "id": r.get("id"),
                "title": r.get("title"),
                "folder": r.get("folder"),
                "description": r.get("description"),
                "keywords": r.get("keywords"),
                "learned_keywords": r.get("learned_keywords"),
            }
            for r in routes
            if r.get("id") != "chat-inbox"
        ],
        sort_keys=True,
    )
    return str(hash(blob))


def _encode(texts: list[str]) -> list[list[float]]:
    model = _load_model()
    if model is None:
        return []
    # Document-side encode (no query prefix) — topics and chats are both "passages".
    vecs = model.encode(texts, normalize_embeddings=True)
    return [v.tolist() for v in vecs]


def ensure_topic_index(cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Return {ids, vectors, fingerprint} cached on disk, rebuilding if needed."""
    routes = [r for r in cfg.get("routes", []) if r.get("id") and r.get("id") != "chat-inbox"]
    if not routes:
        return None
    fp = _fingerprint(routes)
    cache = None
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, json.JSONDecodeError):
        cache = None
    if cache and cache.get("fingerprint") == fp and cache.get("ids"):
        return cache

    profiles = [_topic_profile(r) for r in routes]
    vectors = _encode(profiles)
    if len(vectors) != len(routes):
        return None
    cache = {
        "fingerprint": fp,
        "ids": [r["id"] for r in routes],
        "vectors": vectors,
        "model": os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
    }
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except OSError as e:
        print(f"topic_embed: could not write cache: {e}")
    return cache


def embed_match(
    text: str,
    cfg: dict[str, Any],
    *,
    threshold: float | None = None,
) -> tuple[dict[str, Any] | None, float]:
    """Best non-inbox topic by embedding similarity, or (None, score)."""
    threshold = ASSIGN_THRESHOLD if threshold is None else threshold
    index = ensure_topic_index(cfg)
    if not index:
        return None, 0.0
    vecs = _encode([text[:2000]])
    if not vecs:
        return None, 0.0
    q = vecs[0]
    best_i = -1
    best = -1.0
    second = -1.0
    for i, v in enumerate(index["vectors"]):
        s = _cosine(q, v)
        if s > best:
            second = best
            best = s
            best_i = i
        elif s > second:
            second = s
    # Require a clear winner so weak/ambiguous chats stay in Chat Inbox.
    margin = float(os.environ.get("TOPIC_EMBED_MARGIN", "0.04"))
    if best_i < 0 or best < threshold or (best - second) < margin:
        return None, best
    rid = index["ids"][best_i]
    route = next((r for r in cfg.get("routes", []) if r.get("id") == rid), None)
    return route, best


_WORD = re.compile(r"[a-z][a-z0-9\-]{3,}")

# Tokens that make a bigram low-signal even if the other token is topical.
_WEAK_BIGRAM_TOKENS = {
    "recently", "basically", "alright", "okay", "please", "thanks", "something",
    "anything", "everything", "notes", "project", "projects", "setup", "today",
    "tomorrow", "yesterday", "still", "maybe", "probably", "actually", "really",
    # connectors / deixis / fragment glue
    "because", "then", "these", "those", "them", "this", "that", "before", "after",
    "when", "where", "which", "than", "also", "into", "from", "with", "about",
    "year", "years", "ideas", "helps", "help", "steps", "step", "folder", "folders",
    "interrupted", "source", "here", "there", "very", "just", "such", "same",
    # more low-signal glue seen in live auto-learn
    "each", "every", "main", "personal", "find", "open",
    # skill-boilerplate / status glue that pulled sessions into agent-tooling
    "mode", "status", "scan", "browser", "automation", "cities",
    "designs", "usage", "token",
}

# Exact phrases that repeatedly re-pollute routes even when tokens look topical.
_BLOCKED_LEARN_PHRASES = {
    "review status",
    "student transtioning",
    "security scan",
    "semgrep scan",
    "semgrep security",
    "impeccable designs",
    "impeccable skill",
    "chrome browser",
    "browser automation",
    "in-app browser",
    "auto mode",
    "default mode",
    "voice mode",
    "these cities",
    "open data",
    "source audited",
    "into obsidian",
    "commit callender",
    "analyze this video",
}

_VOWELS = set("aeiou")
# Catch mashed file-type blobs like packdocxpdf without killing creatorflow-style names.
_EXT_MASH = re.compile(r"(pdf|docx?|xlsx?|pptx?|png|jpe?g|gif|zip|json|xml|html|csv|txt)")


def _edit_distance(a: str, b: str) -> int:
    """Tiny Levenshtein for near-duplicate / typo checks on short phrases."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if abs(len(a) - len(b)) > 2:
        return 99
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            ins = cur[j - 1] + 1
            delete = prev[j] + 1
            sub = prev[j - 1] + (ca != cb)
            cur.append(min(ins, delete, sub))
        prev = cur
    return prev[-1]


def _is_noisy_token(tok: str) -> bool:
    """Reject typo-y / mashed / path-ish single tokens."""
    if tok in STOP or tok in _WEAK_BIGRAM_TOKENS:
        return True
    if "users" in tok or "download" in tok or "onedrive" in tok:
        return True
    if tok.isdigit():
        return True
    # Absurd mashed concatenations (keep creatorflow-length product names).
    if len(tok) >= 14 and "-" not in tok:
        return True
    # File-type mashups: packdocxpdf, reportpdf, etc. (allow jsonschema-style prefixes).
    if "-" not in tok and len(tok) >= 8:
        ext_hits = list(_EXT_MASH.finditer(tok))
        if len(ext_hits) >= 2:
            return True
        for m in ext_hits:
            # Extension glued at end (foopdf) or embedded mid-token (abpdfcd).
            if m.end() == len(tok) and m.start() > 0:
                return True
            if m.start() > 0 and m.end() < len(tok):
                return True
    # No-vowel blobs that are not short acronyms.
    if len(tok) >= 6 and "-" not in tok and not any(c in _VOWELS for c in tok):
        return True
    return False


def _is_junk_phrase(phrase: str) -> bool:
    """Drop stutter bigrams and other obvious auto-learn junk."""
    toks = phrase.split()
    if len(toks) != 2:
        return True
    a, b = toks
    if a == b:
        return True  # "doctor doctor", "eval eval"
    if phrase in _BLOCKED_LEARN_PHRASES:
        return True
    if _is_noisy_token(a) or _is_noisy_token(b):
        return True
    if len(phrase) < 7 or len(phrase) > 40:
        return True
    return False


def _near_duplicate(phrase: str, existing: set[str]) -> bool:
    """True when phrase is a typo / reorder of an already-known keyword."""
    pt = phrase.split()
    ps = set(pt)
    for ex in existing:
        if not ex:
            continue
        if phrase == ex:
            return True
        et = ex.split()
        if set(et) == ps:
            return True
        # Whole-phrase near-typo (commit callender ~ commit calendar).
        if abs(len(phrase) - len(ex)) <= 2 and _edit_distance(phrase, ex) <= 2:
            return True
        # Same partner token, other token is a 1–2 edit typo.
        if len(pt) == 2 and len(et) == 2:
            if pt[0] == et[0] and _edit_distance(pt[1], et[1]) <= 2:
                return True
            if pt[1] == et[1] and _edit_distance(pt[0], et[0]) <= 2:
                return True
    return False


def _candidates(text: str) -> list[str]:
    words = [w for w in _WORD.findall((text or "").casefold()) if w not in STOP]
    words = [w for w in words if not _is_noisy_token(w)]
    out: list[str] = []
    seen: set[str] = set()
    # Prefer multi-word phrases only — much less noisy for auto-learning.
    for a, b in zip(words, words[1:]):
        phrase = f"{a} {b}"
        if phrase in seen or _is_junk_phrase(phrase):
            continue
        seen.add(phrase)
        out.append(phrase)
    return out[:25]


def _all_other_keywords(cfg: dict[str, Any], topic_id: str) -> set[str]:
    owned: set[str] = set()
    for r in cfg.get("routes", []):
        if r.get("id") == topic_id:
            continue
        for k in (r.get("keywords") or []) + (r.get("learned_keywords") or []):
            owned.add((k or "").casefold())
    return owned


def learn_keywords(
    text: str,
    route: dict[str, Any],
    cfg: dict[str, Any],
    *,
    score: float,
    source: str = "embed",
) -> list[str]:
    """Persist high-signal phrases onto the route's learned_keywords list.

    Returns the list of newly added keywords (possibly empty).
    """
    if score < LEARN_THRESHOLD:
        return []
    if route.get("id") in (None, "chat-inbox"):
        return []

    existing = {
        (k or "").casefold()
        for k in (route.get("keywords") or []) + (route.get("learned_keywords") or [])
    }
    blocked = _all_other_keywords(cfg, route["id"])
    added: list[str] = []
    learned = list(route.get("learned_keywords") or [])

    profile = _topic_profile(route).casefold()
    profile_tokens = set(_WORD.findall(profile))
    for phrase in _candidates(text):
        if len(added) >= MAX_NEW_KEYWORDS_PER_CHAT:
            break
        if phrase in existing or phrase in blocked:
            continue
        if _is_junk_phrase(phrase):
            continue
        if _near_duplicate(phrase, existing) or _near_duplicate(phrase, blocked):
            continue
        # Must actually appear in the chat text
        if phrase not in text.casefold():
            continue
        # Must share a token with the topic profile (title/keywords/description)
        phrase_tokens = set(phrase.split())
        if not (phrase_tokens & profile_tokens):
            continue
        learned.append(phrase)
        existing.add(phrase)
        added.append(phrase)

    if not added:
        return []

    # Cap learned list
    if len(learned) > MAX_LEARNED_KEYWORDS_PER_TOPIC:
        learned = learned[-MAX_LEARNED_KEYWORDS_PER_TOPIC:]

    # Write back to topic_routes.json
    try:
        with open(ROUTES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for r in data.get("routes", []):
            if r.get("id") == route["id"]:
                r["learned_keywords"] = learned
                # Keep keyword matcher hot: merge learned into keywords used at runtime
                # without duplicating seed keywords.
                seed = list(r.get("keywords") or [])
                seed_cf = {k.casefold() for k in seed}
                for k in learned:
                    if k.casefold() not in seed_cf:
                        seed.append(k)
                        seed_cf.add(k.casefold())
                r["keywords"] = seed
                break
        with open(ROUTES_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        # Invalidate embedding cache fingerprint on next ensure_topic_index
        try:
            if os.path.exists(CACHE_PATH):
                os.remove(CACHE_PATH)
        except OSError:
            pass
        with open(LEARN_LOG, "a", encoding="utf-8") as log:
            log.write(
                f"{source}\tscore={score:.3f}\ttopic={route.get('id')}\tadded={added}\n"
            )
        # Update in-memory route too
        for r in data.get("routes", []):
            if r.get("id") == route["id"]:
                route["learned_keywords"] = list(r.get("learned_keywords") or [])
                route["keywords"] = list(r.get("keywords") or [])
                break
    except (OSError, json.JSONDecodeError, StopIteration) as e:
        print(f"topic_embed: learn_keywords failed: {e}")
        return []
    return added
