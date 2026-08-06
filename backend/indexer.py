"""Shared vault -> ChromaDB indexing implementation.

This is the single implementation used by both the FastAPI backend's
/api/index endpoint (main.py) and the scripts/rebuild_rag_index.py CLI, so
there is exactly one chunking/embedding scheme instead of two drifting
copies.
"""
import os
import re
import sys

import config

# ── Directories to skip entirely ────────────────────────────────────────────
EXCLUDE_DIRS = {
    ".obsidian", ".smart-env", "Templates",
    "99 Archive", "99 Import Logs", "Obsidian Vault Backup",
    "06 Exports",
}

# ── Per-file read timeout (seconds, POSIX only) ─────────────────────────────
FILE_TIMEOUT = 5

# ── Chunking scheme (words, not chars) ──────────────────────────────────────
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

BATCH_SIZE = 100

# ChromaDB's storage layer can perturb stored floats by 1 ULP (~2.4e-7 s at
# current epoch values), so an exact == on mtime would re-embed the affected
# files on every incremental run forever. Real edits move mtime by far more
# than a microsecond, so compare with a small tolerance instead.
MTIME_TOLERANCE = 1e-6


def is_dataless_file(path: str) -> bool:
    """Detect cloud placeholders without triggering a file download."""
    if sys.platform == "win32":
        try:
            import ctypes
            attrs = ctypes.windll.kernel32.GetFileAttributesW(path)
            if attrs != -1:
                # 0x1000: FILE_ATTRIBUTE_OFFLINE
                # 0x00400000: FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
                return bool(attrs & (0x1000 | 0x00400000))
            return False
        except Exception:
            return False
    else:
        dataless_flag = 0x40000000
        try:
            return bool(getattr(os.stat(path), "st_flags", 0) & dataless_flag)
        except OSError:
            return False


def _timeout_handler(signum, frame):
    raise TimeoutError("File read timed out")


def safe_read(filepath: str):
    """Read a file with a hard timeout on POSIX. Returns None on timeout/error."""
    if sys.platform == "win32":
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None
    else:
        import signal
        import threading

        # SIGALRM can only be armed from the main thread; the FastAPI
        # /api/index path calls this from a worker thread, where we fall
        # back to a plain read instead of crashing.
        use_alarm = threading.current_thread() is threading.main_thread()
        if use_alarm:
            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(FILE_TIMEOUT)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return f.read()
        except TimeoutError:
            return None
        except Exception:
            return None
        finally:
            if use_alarm:
                signal.alarm(0)


def extract_frontmatter_tags(content: str):
    """Pull tags from YAML frontmatter if present, else inline #tags in the body."""
    fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not fm_match:
        return []
    fm = fm_match.group(1)

    # tags: [tag1, tag2]
    inline = re.search(r"^tags:\s*\[([^\]]+)\]", fm, re.MULTILINE)
    if inline:
        return [t.strip().lstrip("#") for t in inline.group(1).split(",")]

    # tags:\n  - tag1\n  - tag2
    block_match = re.search(r"^tags:\s*\n((?:\s+-[^\n]+\n?)+)", fm, re.MULTILINE)
    if block_match:
        return [
            re.sub(r"^\s*-\s*#?", "", line).strip()
            for line in block_match.group(1).splitlines()
            if line.strip()
        ]

    # Inline tags in body: #tag
    body_tags = re.findall(r"(?<!\w)#([A-Za-z][A-Za-z0-9_/-]*)", content)
    return list(dict.fromkeys(body_tags))  # dedupe, preserve order


HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def split_sections(text):
    """Split markdown into sections at ATX headings.

    Each section is {"heading": str, "text": str}; the heading line stays in
    its own section's text so it gets embedded with the content it titles.
    Content before the first heading (including YAML frontmatter) is a
    preamble section with heading "". Heading-looking lines inside ``` or
    ~~~ code fences do not split — chat transcripts are full of # comments.
    """
    sections = []
    heading = ""
    lines = []
    in_fence = False

    def close():
        if any(l.strip() for l in lines):
            sections.append({"heading": heading, "text": "\n".join(lines)})

    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            lines.append(line)
            continue
        match = None if in_fence else HEADING_RE.match(line)
        if match:
            close()
            heading = match.group(2).strip()
            lines = [line]
        else:
            lines.append(line)
    close()
    return sections


def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Heading-aware chunking: one coherent topic per chunk.

    Small adjacent sections merge until the word cap; a single oversized
    section falls back to the plain word window (with overlap) so nothing
    exceeds the cap. Returns [{"text": str, "heading": str}].
    """
    chunks = []
    pending_texts = []
    pending_words = 0
    pending_heading = ""

    def flush():
        nonlocal pending_texts, pending_words, pending_heading
        if pending_texts:
            chunks.append({"text": "\n".join(pending_texts), "heading": pending_heading})
        pending_texts, pending_words, pending_heading = [], 0, ""

    for section in split_sections(text):
        words = section["text"].split()
        if len(words) > chunk_size:
            flush()
            for i in range(0, len(words), chunk_size - overlap):
                piece = " ".join(words[i:i + chunk_size])
                if piece:
                    chunks.append({"text": piece, "heading": section["heading"]})
            continue
        if pending_words + len(words) > chunk_size:
            flush()
        if not pending_texts:
            pending_heading = section["heading"]
        pending_texts.append(section["text"])
        pending_words += len(words)
    flush()
    return chunks


def _should_skip_dir(name: str) -> bool:
    return name in EXCLUDE_DIRS or name.startswith(".")


def _scan_vault(vault_path: str):
    """Yield (rel_path, full_path) for every eligible markdown file in the vault."""
    for root, dirs, files in os.walk(vault_path):
        dirs[:] = [d for d in dirs if not _should_skip_dir(d)]
        for f in files:
            if not f.endswith(".md"):
                continue
            if "Index.md" in f or f == "Vault Health Report.md":
                continue
            full_path = os.path.join(root, f)
            rel_path = os.path.relpath(full_path, vault_path).replace("\\", "/")
            yield rel_path, full_path


def index_vault(collection, model, incremental: bool = True, log=print) -> dict:
    """Scan the vault, (re)embed changed files, and prune deleted/dataless ones.

    incremental=True (default): only re-embeds files whose mtime changed
    since the last run, and prunes any previously-indexed source that is no
    longer on disk or has gone dataless (e.g. an un-synced cloud stub).

    incremental=False: wipes every existing chunk first, then reindexes the
    whole vault from scratch.

    Returns a summary dict: files_scanned, files_skipped, files_reindexed,
    files_pruned, chunks_written.
    """
    vault_path = config.get_vault_path()
    log(f"Scanning vault at {vault_path}...")

    summary = {
        "files_scanned": 0,
        "files_skipped": 0,
        "files_reindexed": 0,
        "files_pruned": 0,
        "chunks_written": 0,
    }

    # ── Snapshot what's already indexed (source -> stored mtime + chunk ids) ──
    existing_by_source = {}
    if incremental:
        try:
            existing = collection.get(include=["metadatas"])
            ids = existing.get("ids") or []
            metadatas = existing.get("metadatas") or []
            for chunk_id, meta in zip(ids, metadatas):
                meta = meta or {}
                source = meta.get("source")
                if not source:
                    continue
                entry = existing_by_source.setdefault(source, {"mtime": meta.get("mtime"), "ids": []})
                entry["ids"].append(chunk_id)
        except Exception as e:
            log(f"Could not read existing index for incremental diff: {e}")
    else:
        # Full wipe-and-rebuild: clear every existing chunk up front.
        try:
            existing = collection.get(include=[])
            all_ids = existing.get("ids") or []
            if all_ids:
                collection.delete(ids=all_ids)
                log(f"Cleared {len(all_ids)} existing chunks for full rebuild.")
        except Exception as e:
            log(f"Could not clear existing collection for full rebuild: {e}")

    valid_sources = set()
    pending_docs, pending_metas, pending_ids = [], [], []

    def flush():
        nonlocal pending_docs, pending_metas, pending_ids
        if not pending_docs:
            return
        for i in range(0, len(pending_docs), BATCH_SIZE):
            b_docs = pending_docs[i:i + BATCH_SIZE]
            b_meta = pending_metas[i:i + BATCH_SIZE]
            b_ids = pending_ids[i:i + BATCH_SIZE]
            try:
                embeddings = model.encode(b_docs).tolist()
                collection.upsert(documents=b_docs, embeddings=embeddings, metadatas=b_meta, ids=b_ids)
                summary["chunks_written"] += len(b_docs)
            except Exception as e:
                log(f"Batch upsert failed: {e}")
        pending_docs, pending_metas, pending_ids = [], [], []

    for rel_path, full_path in _scan_vault(vault_path):
        summary["files_scanned"] += 1

        # Cloud-only stub: skip without triggering a download, and don't
        # count it as "valid" so a previously-indexed copy gets pruned below.
        if is_dataless_file(full_path):
            summary["files_skipped"] += 1
            continue

        valid_sources.add(rel_path)

        try:
            mtime = os.path.getmtime(full_path)
        except OSError as e:
            log(f"  Skipped (stat error): {rel_path}: {e}")
            summary["files_skipped"] += 1
            continue

        prior = existing_by_source.get(rel_path)
        if incremental and prior is not None:
            stored_mtime = prior.get("mtime")
            if (
                isinstance(stored_mtime, (int, float))
                and abs(stored_mtime - mtime) <= MTIME_TOLERANCE
            ):
                continue  # unchanged since last index

        content = safe_read(full_path)
        if content is None:
            log(f"  Skipped (read error): {rel_path}")
            summary["files_skipped"] += 1
            continue

        # Changed (or force-rebuilt) file: drop its old chunks before re-adding.
        had_prior_chunks = bool(incremental and prior is not None and prior.get("ids"))
        if had_prior_chunks:
            try:
                collection.delete(ids=prior["ids"])
            except Exception as e:
                log(f"Could not delete stale chunks for {rel_path}: {e}")

        tags = extract_frontmatter_tags(content)
        tags_str = ",".join(tags)
        title = os.path.splitext(os.path.basename(full_path))[0]
        category = "chat" if "05 AI Chats" in rel_path else "note"

        chunks = chunk_text(content)
        for i, chunk in enumerate(chunks):
            pending_docs.append(chunk)
            pending_metas.append({
                "source": rel_path,
                "title": title,
                "tags": tags_str,
                "category": category,
                "mtime": mtime,
            })
            pending_ids.append(f"{rel_path}_chunk_{i}")

        # A file that yields no chunks (empty/whitespace-only) and had nothing
        # indexed before is a no-op, not a reindex — otherwise it would be
        # re-counted as "reindexed" on every incremental run forever.
        if chunks or had_prior_chunks:
            summary["files_reindexed"] += 1

        if len(pending_docs) >= BATCH_SIZE:
            flush()

    flush()

    # ── Prune anything indexed that is no longer on disk or now dataless ────
    if incremental:
        stale_sources = set(existing_by_source) - valid_sources
        for source in stale_sources:
            stale_ids = existing_by_source[source]["ids"]
            if not stale_ids:
                continue
            try:
                collection.delete(ids=stale_ids)
                summary["files_pruned"] += 1
            except Exception as e:
                log(f"Could not prune stale source {source}: {e}")

    log(
        f"Index complete: {summary['files_scanned']} scanned, "
        f"{summary['files_reindexed']} reindexed, {summary['files_skipped']} skipped, "
        f"{summary['files_pruned']} pruned, {summary['chunks_written']} chunks written."
    )
    return summary
