"""
rebuild_rag_index.py — Second Brain RAG Indexer
Reads the Obsidian vault sequentially to avoid macOS OneDrive timeout storms,
extracts frontmatter tags, chunks text, and builds a ChromaDB vector index.
"""
import os
import re
import sys
import chromadb
from sentence_transformers import SentenceTransformer
import time

# ── Directories to skip entirely ────────────────────────────────────────────
EXCLUDES = [
    ".obsidian", ".smart-env", "Templates",
    "99 Archive", "99 Import Logs", "Obsidian Vault Backup",
    "06 Exports",
]

# ── Per-file read timeout (seconds) — avoids hanging on un-synced files ─────
FILE_TIMEOUT = 5


def _timeout_handler(signum, frame):
    raise TimeoutError("File read timed out")


def is_local_file(filepath: str) -> bool:
    """Return True if the file has local disk blocks (not a cloud-only stub)."""
    if sys.platform == "win32":
        try:
            import ctypes
            attrs = ctypes.windll.kernel32.GetFileAttributesW(filepath)
            if attrs != -1:
                # Check for FILE_ATTRIBUTE_OFFLINE (0x1000) or RECALL_ON_DATA_ACCESS (0x400000)
                is_offline = bool(attrs & 0x1000)
                is_recall = bool(attrs & 0x00400000)
                return not (is_offline or is_recall)
            return True
        except Exception:
            return True
    else:
        try:
            return getattr(os.stat(filepath), "st_blocks", 1) > 0
        except OSError:
            return False


def safe_read(filepath: str) -> str | None:
    """Read a file with a hard timeout. Returns None on timeout or error."""
    if sys.platform == "win32":
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            return content
        except Exception:
            return None
    else:
        import signal
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(FILE_TIMEOUT)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
            return content
        except TimeoutError:
            return None
        except Exception:
            return None
        finally:
            signal.alarm(0)


def extract_frontmatter_tags(content: str) -> list[str]:
    """Pull tags from YAML frontmatter if present."""
    # Match the YAML block at the top of the file
    fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not fm_match:
        return []
    fm = fm_match.group(1)

    # tags: [tag1, tag2]  or  tags:\n  - tag1
    inline = re.search(r"^tags:\s*\[([^\]]+)\]", fm, re.MULTILINE)
    if inline:
        return [t.strip().lstrip("#") for t in inline.group(1).split(",")]

    block_match = re.search(r"^tags:\s*\n((?:\s+-[^\n]+\n?)+)", fm, re.MULTILINE)
    if block_match:
        return [
            re.sub(r"^\s*-\s*#?", "", line).strip()
            for line in block_match.group(1).splitlines()
            if line.strip()
        ]

    # Inline tags in body: #tag
    body_tags = re.findall(r"(?<!\w)#([A-Za-z][A-Za-z0-9_/-]*)", content)
    return list(dict.fromkeys(body_tags))  # deduplicate, preserve order


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i : i + chunk_size])
        if chunk:
            chunks.append(chunk)
    return chunks


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except AttributeError:
            pass

    home_dir = os.path.expanduser("~")
    vault_dir = os.path.join(home_dir, "OneDrive/Documents/Obsidian Vault")
    db_path = os.path.join(home_dir, "IdeaProjects/second-brain-tools/chroma_db")

    print(f"🧠 Second Brain RAG Indexer")
    print(f"   Vault : {vault_dir}")
    print(f"   DB    : {db_path}")
    print()

    print("Initializing ChromaDB...")
    client = chromadb.PersistentClient(path=db_path)

    # Wipe and rebuild
    try:
        client.delete_collection("second_brain")
        print("  ↳ Old 'second_brain' collection deleted.")
    except Exception:
        pass

    collection = client.create_collection("second_brain")

    print("Loading embedding model (all-MiniLM-L6-v2)...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    print("  ↳ Model ready.\n")

    print(f"Scanning vault (timeout {FILE_TIMEOUT}s per file)...")

    documents, metadatas, ids = [], [], []
    file_counter = 0
    skip_counter = 0

    for root, dirs, files in os.walk(vault_dir):
        # Prune excluded directories in-place
        dirs[:] = [d for d in dirs if not any(x in d for x in EXCLUDES)]

        for file in files:
            if not file.endswith(".md"):
                continue

            filepath = os.path.join(root, file)
            rel_path = os.path.relpath(filepath, vault_dir)
            # Fast-path: skip cloud-only stubs without burning the timeout
            if not is_local_file(filepath):
                skip_counter += 1
                continue

            content = safe_read(filepath)

            if content is None:
                print(f"  ⚠ Skipped (read error): {rel_path}")
                skip_counter += 1
                continue

            tags = extract_frontmatter_tags(content)
            chunks = chunk_text(content)
            title = file.removesuffix(".md")
            tags_str = ",".join(tags)

            # Determine category: "chat" if inside 05 AI Chats, else "note"
            is_chat = "05 AI Chats" in rel_path.replace("\\", "/")
            category = "chat" if is_chat else "note"

            for i, chunk in enumerate(chunks):
                documents.append(chunk)
                metadatas.append({
                    "source": rel_path,
                    "title": title,
                    "tags": tags_str,
                    "category": category,
                })
                ids.append(f"{rel_path}_chunk_{i}")

            file_counter += 1
            if file_counter % 25 == 0:
                print(f"  ↳ {file_counter} files scanned, {len(documents)} chunks so far...")

    print(f"\n✓ Scanned {file_counter} files ({skip_counter} skipped), {len(documents)} total chunks.")

    if not documents:
        print("\n❌ No documents indexed. Check vault path and OneDrive sync status.")
        return

    print("Generating embeddings and writing to ChromaDB...")
    batch_size = 100
    total_batches = (len(documents) + batch_size - 1) // batch_size

    for i in range(0, len(documents), batch_size):
        batch_docs = documents[i : i + batch_size]
        batch_ids = ids[i : i + batch_size]
        batch_meta = metadatas[i : i + batch_size]

        embeddings = model.encode(batch_docs).tolist()
        collection.add(ids=batch_ids, embeddings=embeddings, documents=batch_docs, metadatas=batch_meta)

        batch_num = i // batch_size + 1
        print(f"  ↳ Batch {batch_num}/{total_batches}")

    print("\n✅ RAG Index rebuilt successfully!")
    print(f"   {file_counter} notes → {len(documents)} chunks → ChromaDB")


if __name__ == "__main__":
    main()
