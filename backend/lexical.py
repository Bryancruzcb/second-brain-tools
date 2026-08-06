"""In-memory BM25 index over the Chroma chunk corpus.

Built from the same collection the vector leg searches, so both retrieval
legs see identical chunks. Pure Python (rank_bm25), rebuilt at backend
startup and after each ingestion run; goes stale if another process
updates the index until the next rebuild or restart. A build failure
downgrades hybrid retrieval to vector-only — never a crash.
"""
import re

from rank_bm25 import BM25Okapi

TOKEN_RE = re.compile(r"[a-z0-9_]+")


def tokenize(text):
    """Lowercase alphanumeric/underscore tokens; snake_case stays whole."""
    return TOKEN_RE.findall(text.lower())


class LexicalIndex:
    """BM25 over every chunk in the collection, with scope filtering."""

    def __init__(self, entries, bm25):
        self._entries = entries
        self._bm25 = bm25

    @classmethod
    def build(cls, collection):
        got = collection.get(include=["documents", "metadatas"])
        ids = got.get("ids") or []
        docs = got.get("documents") or []
        metas = got.get("metadatas") or []
        entries, corpus = [], []
        for chunk_id, doc, meta in zip(ids, docs, metas):
            meta = meta or {}
            entries.append({
                "id": chunk_id,
                "source": meta.get("source", ""),
                "title": meta.get("title", "Untitled Note"),
                "chunk": doc,
                "category": meta.get("category", "note"),
            })
            corpus.append(tokenize(doc))
        if not entries:
            return cls([], None)
        if not any(corpus):
            # Every document tokenized to nothing (punctuation-only corpus):
            # BM25Okapi divides by an empty vocabulary. Degrade, never crash.
            return cls(entries, None)
        return cls(entries, BM25Okapi(corpus))

    def __len__(self):
        return len(self._entries)

    def search(self, query_text, scope="notes", k=10):
        """Top-k chunks by BM25 score, best first, honoring the scope filter.

        Candidate shape matches retrieval.retrieve() but carries "score"
        (higher better) instead of "distance". Chunks without a positive
        BM25 score are excluded — BM25 has nothing to say about them.
        """
        if self._bm25 is None:
            return []
        tokens = tokenize(query_text)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        out = []
        for i in ranked:
            if scores[i] <= 0:
                break
            entry = self._entries[i]
            if scope == "chats" and entry["category"] != "chat":
                continue
            if scope == "notes" and entry["category"] == "chat":
                continue
            out.append({
                "id": entry["id"],
                "source": entry["source"],
                "title": entry["title"],
                "chunk": entry["chunk"],
                "score": float(scores[i]),
            })
            if len(out) >= k:
                break
        return out
