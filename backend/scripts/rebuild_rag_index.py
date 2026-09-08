"""
rebuild_rag_index.py — Second Brain RAG Indexer CLI

Thin wrapper around the shared indexer.index_vault() implementation.
Defaults to an incremental update (only changed/new/deleted files); pass
--full to wipe and rebuild the whole ChromaDB collection from scratch.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chromadb
from sentence_transformers import SentenceTransformer

import config
import indexer

import urllib.error
import urllib.request



def _notify_backend_lexical_refresh():
    """Ask a running backend to rebuild its in-memory BM25 snapshot.

    rebuild_rag_index writes Chroma out-of-process; the backend's keyword leg
    stays stale until refresh or restart. Best-effort: a down backend is fine
    (next startup rebuilds BM25); only print a note so the nightly log shows it.
    """
    base = os.environ.get("SECOND_BRAIN_API_URL", "http://127.0.0.1:8000").rstrip("/")
    url = f"{base}/api/lexical/refresh"
    try:
        req = urllib.request.Request(url, method="POST", data=b"")
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        print(f"BM25 refresh notified at {url}: {body}")
    except urllib.error.URLError as exc:
        print(f"BM25 refresh skipped (backend not reachable at {url}): {exc}")
    except Exception as exc:
        print(f"BM25 refresh skipped: {exc}")


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    parser = argparse.ArgumentParser(description="Rebuild or update the Second Brain RAG index.")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Wipe the existing collection and reindex the whole vault from scratch "
             "(default: incremental — only changed/new/deleted files).",
    )
    args = parser.parse_args()

    vault_dir = config.get_vault_path()
    db_path = config.get_chroma_path()

    print("Second Brain RAG Indexer")
    print(f"   Vault : {vault_dir}")
    print(f"   DB    : {db_path}")
    print(f"   Mode  : {'full rebuild' if args.full else 'incremental'}")
    print()

    print("Initializing ChromaDB...")
    client = chromadb.PersistentClient(path=db_path)
    collection = client.get_or_create_collection("second_brain")

    model_name = config.get_embedding_model()
    stamped_model = (collection.metadata or {}).get("embedding_model")
    print(f"Index stamp: {stamped_model or '(unstamped)'} | configured: {model_name}")

    print(f"Loading embedding model ({model_name})...")
    model = SentenceTransformer(model_name)
    print("  Model ready.\n")

    summary = indexer.index_vault(collection, model, incremental=not args.full, log=print)

    # Anything that left the index incomplete has to fail the process, or the
    # nightly scheduled task reports success over a half-written index.
    failure = None
    if summary.get("aborted"):
        failure = f"index aborted: {summary['aborted']}"
    elif summary["batches_failed"] > 0:
        failure = (
            f"{summary['batches_failed']} embedding batch(es) failed — the index is "
            "incomplete; see the errors above and rerun."
        )
    elif summary["chunks_written"] == 0 and summary["files_reindexed"] > 0:
        failure = (
            f"{summary['files_reindexed']} file(s) were reindexed but 0 chunks were "
            "written — nothing reached the index."
        )
    elif summary.get("wipe_failed"):
        failure = (
            "the full-rebuild wipe failed, so old-model chunks may still be mixed "
            "into the index (it was deliberately left unstamped); close anything "
            "holding the Chroma store and rerun --full."
        )

    if failure:
        print(f"\nFAILED: {failure}")
        sys.exit(1)

    # Even a no-op scan can follow an earlier out-of-process write; always ask
    # the live backend to resync BM25 when we finish cleanly.
    _notify_backend_lexical_refresh()

    if summary["chunks_written"] == 0 and summary["files_reindexed"] == 0:
        print("\nNo changes to index.")
    else:
        print("\nRAG index updated successfully!")
        print(
            f"   {summary['files_scanned']} files scanned, "
            f"{summary['files_reindexed']} reindexed, "
            f"{summary['files_skipped']} skipped, "
            f"{summary['files_pruned']} pruned, "
            f"{summary['chunks_written']} chunks written."
        )


if __name__ == "__main__":
    main()
