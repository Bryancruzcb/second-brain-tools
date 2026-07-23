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

    print("Loading embedding model (all-MiniLM-L6-v2)...")
    model = SentenceTransformer("all-MiniLM-L6-v2")
    print("  Model ready.\n")

    summary = indexer.index_vault(collection, model, incremental=not args.full, log=print)

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
