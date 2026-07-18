#!/usr/bin/env python3
"""Rebuild the same content-first ChromaDB collection used by the backend API."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sentence_transformers import SentenceTransformer

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from indexing import rebuild_index  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", help="Override OBSIDIAN_VAULT_PATH")
    parser.add_argument("--database", help="Override SECOND_BRAIN_DB_PATH")
    parser.add_argument("--model", default="all-MiniLM-L6-v2")
    args = parser.parse_args()

    print(f"Loading embedding model {args.model}...")
    model = SentenceTransformer(args.model)
    collection, summary = rebuild_index(
        model=model,
        vault_path=args.vault,
        database_path=args.database,
    )
    print(json.dumps(summary.as_dict(), indent=2))
    print(f"RAG index ready with {collection.count()} content chunk(s).")
    print("Restart the backend after a standalone rebuild so it reopens the swapped collection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
