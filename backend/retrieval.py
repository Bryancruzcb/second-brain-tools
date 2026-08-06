"""Shared retrieval: the one code path both /api/query and the eval use.

Extracted from main.py's run_query so the eval harness measures exactly
what the app does — same reason indexer.py was unified in PR #3.
"""

TOP_K = 4


def scope_filter(scope):
    """Chroma where-filter for a search scope ("notes" | "chats" | "all")."""
    if scope == "chats":
        return {"category": "chat"}
    if scope == "notes":
        return {"category": {"$ne": "chat"}}
    return None


def retrieve(query_text, *, model, collection, scope="notes", k=TOP_K):
    """Embed query_text and return the top-k chunk candidates, best first.

    Returns a list of {"source", "title", "chunk", "distance"} dicts.
    """
    query_embedding = model.encode([query_text]).tolist()
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=k,
        where=scope_filter(scope),
    )
    candidates = []
    if results and results.get("documents") and results["documents"]:
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        dists = (results.get("distances") or [[0.0] * len(docs)])[0]
        for doc, meta, dist in zip(docs, metas, dists):
            meta = meta or {}
            candidates.append({
                "source": meta.get("source", ""),
                "title": meta.get("title", "Untitled Note"),
                "chunk": doc,
                "distance": float(dist),
            })
    return candidates
