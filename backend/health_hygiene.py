"""Derive vault Repair-panel hygiene lists from ChromaDB graph data."""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional, Set, Tuple

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")

def is_chat_note(rel_path: str) -> bool:
    return rel_path.replace("\\", "/").startswith("05 AI Chats/")

def suggest_tags(title: str, content: str) -> List[str]:
    blob = f"{title} {content}".lower()
    out: List[str] = []
    if any(k in blob for k in ("essay","thesis","class","course","lecture","university","college")): out.append("#school")
    if any(k in blob for k in ("react","python","javascript","code","git","api","sql","node")): out.append("#coding")
    if any(k in blob for k in ("subscription","finance","bill","personal","bank")): out.append("#personal")
    if any(k in blob for k in ("obsidian","rag","embedding","vector","prompt")): out.append("#second-brain")
    return out

def register_note_aliases(alias_map, source, title):
    stem = source[:-3] if source.lower().endswith(".md") else source
    for key in (title, stem, source, stem.replace("\\", "/"), source.replace("\\", "/"), os.path.basename(stem)):
        if key: alias_map[key.lower()] = source

def derive_hygiene_from_chunks(nodes, metadatas, documents):
    alias_map = {}
    content_by_source = {}
    node_by_id = {n["id"]: n for n in nodes}
    directed_incoming = {n["id"]: set() for n in nodes}
    for node in nodes:
        register_note_aliases(alias_map, node["id"], node.get("label") or node["id"])
    for meta, doc in zip(metadatas, documents):
        source = (meta or {}).get("source", "")
        if not source: continue
        if doc and len(content_by_source.get(source, "")) < 4000:
            content_by_source[source] = (content_by_source.get(source, "") + "\n" + doc)[:4000]
    broken_link_set = set()
    for meta, doc in zip(metadatas, documents):
        source = (meta or {}).get("source", "")
        if not source or not doc: continue
        label = node_by_id.get(source, {}).get("label", source)
        for match in WIKILINK_RE.finditer(doc):
            raw_target = match.group(1).strip()
            if not raw_target or raw_target.startswith("#"): continue
            target_key = raw_target.lower().split("#", 1)[0]
            target_source = alias_map.get(target_key)
            if target_source and target_source != source:
                directed_incoming.setdefault(target_source, set()).add(source)
            elif not target_source and not is_chat_note(source):
                broken_link_set.add((source, label, raw_target))
    broken_links = [{"source": s, "source_title": t, "target": tgt} for (s, t, tgt) in sorted(broken_link_set)]
    orphaned_notes = []
    tagless_notes = []
    for node in nodes:
        path = node["id"]
        title = node.get("label") or path
        if is_chat_note(path): continue
        if len(directed_incoming.get(path, set())) == 0 and "Home" not in path and "Index.md" not in path:
            orphaned_notes.append({"path": path, "title": title})
        if not node.get("tags"):
            tagless_notes.append({"path": path, "title": title, "suggestions": suggest_tags(title, content_by_source.get(path, ""))})
    orphaned_notes.sort(key=lambda n: n["title"].lower())
    tagless_notes.sort(key=lambda n: n["title"].lower())
    return {"broken_links": broken_links, "orphaned_notes": orphaned_notes, "tagless_notes": tagless_notes}

def find_vault_core_binary(repo_root=None):
    import shutil
    for name in ("vault-core", "vault-core.exe"):
        found = shutil.which(name)
        if found: return found
    if repo_root is None:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(repo_root, "core", "target", "release", "vault-core.exe"),
        os.path.join(repo_root, "core", "target", "release", "vault-core"),
        os.path.join(home, "IdeaProjects", "second-brain-tools", "core", "target", "release", "vault-core.exe"),
        os.path.join(home, "IdeaProjects", "second-brain-tools", "core", "target", "release", "vault-core"),
    ]
    for candidate in candidates:
        if os.path.exists(candidate): return candidate
    return None
