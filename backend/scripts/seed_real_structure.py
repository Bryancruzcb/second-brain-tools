#!/usr/bin/env python3
"""Compatibility entry point for the former metadata-only graph seeder.

The old implementation replaced transcript content with placeholder sentences. It now
delegates to the real content indexer so running an older command cannot degrade RAG.
"""

from rebuild_rag_index import main


if __name__ == "__main__":
    print("The structural seeder is deprecated; rebuilding the content index instead.")
    raise SystemExit(main())
