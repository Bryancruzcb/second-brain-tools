"""Saved Ask history: every answered question, newest first.

Recorded inside the backend's query path, so asks from the web UI, the
Obsidian plugin and the MCP query_vault tool all land in one list. Stored
as a small JSON file (config.get_ask_history_path(), gitignored) and capped
at config.get_ask_history_max() entries, oldest dropped first. Writes go to
a temp file and are swapped in with os.replace, so a crash mid-write leaves
the previous file intact.

Disabled on READ_ONLY deployments: those serve an unauthenticated API, and
a shared history would show one visitor's questions to the next.
"""
import json
import logging
import os
import tempfile
import threading
import time
import uuid

import config

logger = logging.getLogger(__name__)

SNIPPET_CHARS = 240
_lock = threading.Lock()


def enabled() -> bool:
    return not config.read_only()


def _load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as e:
        logger.warning("Ask history at %s is unreadable, starting fresh: %s", path, e)
        return []
    entries = data.get("entries") if isinstance(data, dict) else data
    return [e for e in entries or [] if isinstance(e, dict) and e.get("id")]


def _save(path, entries):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".ask_history.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "entries": entries}, f, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _trim_source(source):
    snippet = source.get("snippet") or ""
    if len(snippet) > SNIPPET_CHARS:
        snippet = snippet[:SNIPPET_CHARS].rstrip() + "..."
    return {
        "title": source.get("title") or "",
        "source": source.get("source") or "",
        "snippet": snippet,
    }


def record(question, answer, sources, *, scope="notes", context_nodes=None, now=None):
    """Save one answered Ask and return the entry; None when disabled or on error.

    Never raises: a history failure must not fail the Ask it describes.
    """
    if not enabled() or not (question or "").strip():
        return None
    ts = time.time() if now is None else now
    entry = {
        "id": uuid.uuid4().hex,
        "asked_at": ts,
        "question": question.strip(),
        "answer": answer or "",
        "scope": scope or "notes",
        "sources": [_trim_source(s) for s in sources or []],
    }
    if context_nodes:
        entry["context_nodes"] = list(context_nodes)
    path = config.get_ask_history_path()
    try:
        with _lock:
            entries = _load(path)
            entries.insert(0, entry)
            del entries[config.get_ask_history_max():]
            _save(path, entries)
    except Exception as e:
        logger.warning("Could not save Ask history to %s: %s", path, e)
        return None
    return entry


def list_entries(limit=None):
    """Saved asks, newest first."""
    if not enabled():
        return []
    with _lock:
        entries = _load(config.get_ask_history_path())
    return entries[:limit] if limit else entries


def delete(entry_id):
    """Remove one entry; True if it existed."""
    path = config.get_ask_history_path()
    with _lock:
        entries = _load(path)
        kept = [e for e in entries if e.get("id") != entry_id]
        if len(kept) == len(entries):
            return False
        _save(path, kept)
    return True


def clear():
    """Remove every entry; returns how many were removed."""
    path = config.get_ask_history_path()
    with _lock:
        removed = len(_load(path))
        if os.path.exists(path):
            _save(path, [])
    return removed
