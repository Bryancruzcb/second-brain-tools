"""
topic_router.py — map exported AI chats to related vault topic folders.

Transcripts stay under 05 AI Chats/. For a matching topic, we write/update a
small stub note in that topic's AI Chat Links/ folder that points at the
transcript. Keywords win first; otherwise embeddings pick a topic (or Chat Inbox).
Confident matches auto-append learned_keywords into topic_routes.json.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

import sb_common

try:
    import topic_embed
except Exception:  # pragma: no cover
    topic_embed = None  # type: ignore

ROUTES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "topic_routes.json")


def _load_config() -> dict[str, Any]:
    try:
        with open(ROUTES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"topic_router: could not load {ROUTES_PATH}: {e}")
        return {"routes": [], "stub_subdir": "AI Chat Links"}


def vault_wikilink(abs_path: str) -> str:
    """Absolute vault file -> wikilink path without .md."""
    vault = sb_common.get_vault_path()
    rel = os.path.relpath(abs_path, vault)
    rel = rel.replace("\\", "/")
    if rel.lower().endswith(".md"):
        rel = rel[:-3]
    return rel


def _keyword_hit(haystack: str, keyword: str) -> bool:
    """Casefold substring match with word-ish boundaries for short tokens."""
    k = (keyword or "").strip().casefold()
    if not k:
        return False
    h = (haystack or "").casefold()
    # Multi-word / hyphenated phrases: plain substring is enough.
    if " " in k or "-" in k or len(k) >= 5:
        return k in h
    # Short tokens like "rag" must not match inside "storage" / "paragraph".
    return re.search(rf"(?<!\w){re.escape(k)}(?!\w)", h) is not None


def match_route(text: str, config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Return the best matching route for text, or None.

    Scoring: longest matching keyword wins (more specific phrases beat short
    ones). Ties keep the first route in topic_routes.json order.
    """
    cfg = config or _load_config()
    best = None
    best_len = -1
    for route in cfg.get("routes", []):
        for kw in route.get("keywords", []):
            k = (kw or "").strip()
            if not _keyword_hit(text, k):
                continue
            if len(k) > best_len:
                best = route
                best_len = len(k)
    return best


def project_wikilink(text: str) -> str:
    """Wikilink for chat-index Project column, or empty string."""
    route = match_route(text)
    if not route:
        return ""
    title = route.get("title") or route.get("id") or ""
    return f"[[{title}]]" if title else ""


def _stub_body(
    *,
    title: str,
    source: str,
    date_str: str,
    short_id: str,
    topic_title: str,
    transcript_link: str,
    excerpt: str,
) -> str:
    excerpt = re.sub(r"\s+", " ", (excerpt or "").strip())
    if len(excerpt) > 280:
        excerpt = excerpt[:277].rstrip() + "..."
    return (
        "---\n"
        "type: chat-link\n"
        f'source: "{source.lower()}"\n'
        f'session_id: "{short_id}"\n'
        f'topic: "{topic_title}"\n'
        f'date: "{date_str}"\n'
        "tags:\n"
        "  - ai-chat-link\n"
        f'  - "{source.lower()}"\n'
        "---\n"
        f"# Chat: {title}\n\n"
        f"- Topic: [[{topic_title}]]\n"
        f"- Transcript: [[{transcript_link}|{title}]]\n"
        f"- Source: {source}\n"
        f"- Date: {date_str}\n"
        f"- Session: `{short_id}`\n\n"
        "## Opening\n\n"
        f"> {excerpt}\n"
    )


def write_stub(
    *,
    route: dict[str, Any],
    source: str,
    title: str,
    date_str: str,
    short_id: str,
    transcript_link: str,
    first_prompt: str,
    config: dict[str, Any] | None = None,
) -> str | None:
    """Write/update the stub note. Returns absolute stub path, or None."""
    cfg = config or _load_config()
    folder = route.get("folder")
    if not folder:
        return None
    stub_subdir = cfg.get("stub_subdir") or "AI Chat Links"
    vault = sb_common.get_vault_path()
    dest_dir = os.path.join(vault, *folder.replace("\\", "/").split("/"), stub_subdir)
    os.makedirs(dest_dir, exist_ok=True)

    safe_title = sb_common.clean_filename(title, "Untitled Session")
    stub_name = f"{date_str} - {safe_title} - {short_id}.md"
    stub_path = os.path.join(dest_dir, stub_name)

    # If a stub for this session already exists under this topic (maybe renamed),
    # refresh that file in place instead of creating a duplicate.
    existing = None
    sid = short_id.lower()
    try:
        for name in os.listdir(dest_dir):
            if name.lower().endswith(".md") and sid in name.lower():
                existing = os.path.join(dest_dir, name)
                break
    except OSError:
        pass
    if existing:
        stub_path = existing

    topic_title = route.get("title") or route.get("id") or "Topic"
    body = _stub_body(
        title=safe_title,
        source=source,
        date_str=date_str,
        short_id=short_id,
        topic_title=topic_title,
        transcript_link=transcript_link,
        excerpt=first_prompt,
    )
    with open(stub_path, "w", encoding="utf-8") as f:
        f.write(body)
    return stub_path


def route_chat(
    *,
    source: str,
    title: str,
    date_str: str,
    short_id: str,
    first_prompt: str,
    transcript_path: str | None = None,
    transcript_link: str | None = None,
    category: str | None = None,
) -> dict[str, Any] | None:
    """Classify a chat and write a topic stub when it matches a route.

    Pass transcript_path (absolute) and/or transcript_link (vault wikilink).
    Returns {"route", "stub_path", "project"} or None if no topic matched.
    """
    parts = [title, first_prompt]
    if category:
        parts.append(str(category))
    text = "\n".join(p for p in parts if p)
    cfg = _load_config()

    score = 1.0  # keyword hits count as strong
    how = "keyword"
    route = match_route(text, cfg)

    if route is None and topic_embed is not None:
        route, score = topic_embed.embed_match(text, cfg)
        how = "embed"
        if route is not None:
            print(f"Topic embed: {route.get('id')} score={score:.3f}")

    if route is None:
        default_id = cfg.get("default_route_id")
        if default_id:
            route = next((r for r in cfg.get("routes", []) if r.get("id") == default_id), None)
            how = "inbox"
            score = 0.0
        if not route:
            return None

    # Grow keyword map automatically for confident non-inbox assignments.
    if topic_embed is not None and route.get("id") != "chat-inbox":
        learn_score = score if how == "embed" else topic_embed.LEARN_THRESHOLD
        # For keyword hits, still try learning at learn threshold using embed score if available.
        if how == "keyword" and topic_embed is not None:
            try:
                _, emb_score = topic_embed.embed_match(text, cfg, threshold=0.0)
                learn_score = max(learn_score, emb_score)
            except Exception:
                learn_score = topic_embed.LEARN_THRESHOLD
        try:
            added = topic_embed.learn_keywords(
                text, route, cfg, score=learn_score, source=how
            )
            if added:
                print(f"Topic keywords learned for {route.get('id')}: {added}")
                # refresh route from disk so stub uses updated title map
                cfg = _load_config()
                route = next(
                    (r for r in cfg.get("routes", []) if r.get("id") == route.get("id")),
                    route,
                )
        except Exception as e:
            print(f"topic keyword learn skipped: {e}")

    link = transcript_link
    if not link and transcript_path:
        link = vault_wikilink(transcript_path)
    if not link:
        return None

    stub_path = write_stub(
        route=route,
        source=source,
        title=title,
        date_str=date_str,
        short_id=short_id,
        transcript_link=link,
        first_prompt=first_prompt,
        config=cfg,
    )
    if not stub_path:
        return None

    project = f"[[{route.get('title') or route.get('id')}]]"
    print(f"Topic stub: {os.path.relpath(stub_path, sb_common.get_vault_path())} <- {route.get('id')}")
    return {"route": route, "stub_path": stub_path, "project": project}


if __name__ == "__main__":
    import sys
    sample = " ".join(sys.argv[1:]) or "how does my rag system and second brain auto_archive work"
    r = match_route(sample)
    print(r["id"] if r else "no match", "<-", sample[:80])
