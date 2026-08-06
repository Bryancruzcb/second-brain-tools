"""Shared retrieval: the one code path both /api/query and the eval use.

Extracted from main.py's run_query so the eval harness measures exactly
what the app does — same reason indexer.py was unified in PR #3.
"""

TOP_K = 4
HYBRID_DEPTH = 20
RRF_K = 60
RERANK_DEPTH = 20


def scope_filter(scope):
    """Chroma where-filter for a search scope ("notes" | "chats" | "all")."""
    if scope == "chats":
        return {"category": "chat"}
    if scope == "notes":
        return {"category": {"$ne": "chat"}}
    return None


def retrieve(query_text, *, model, collection, scope="notes", k=TOP_K):
    """Embed query_text and return the top-k chunk candidates, best first.

    Returns a list of {"id", "source", "title", "chunk", "distance"} dicts.
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
        ids = (results.get("ids") or [[""] * len(docs)])[0]
        for doc, meta, dist, chunk_id in zip(docs, metas, dists, ids):
            meta = meta or {}
            candidates.append({
                "id": chunk_id,
                "source": meta.get("source", ""),
                "title": meta.get("title", "Untitled Note"),
                "chunk": doc,
                "distance": float(dist),
            })
    return candidates


def rrf_fuse(ranked_lists, k=TOP_K, rrf_k=RRF_K):
    """Reciprocal Rank Fusion over best-first candidate lists.

    Fuses by chunk identity — "id" when non-empty, else (source, chunk).
    An item appearing in several lists sums 1/(rrf_k + rank) across them,
    which rewards agreement without needing comparable scores. Ties break
    by first insertion, i.e. the earlier list's ordering.
    """
    scores = {}
    first_seen = {}
    for lst in ranked_lists:
        for rank, cand in enumerate(lst, start=1):
            key = cand.get("id") or (cand["source"], cand["chunk"])
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
            if key not in first_seen:
                first_seen[key] = cand
    ranked = sorted(scores, key=scores.get, reverse=True)
    return [first_seen[key] for key in ranked[:k]]


def rerank(query_text, candidates, *, cross_encoder, k=TOP_K):
    """Second-stage precision: re-sort candidates by cross-encoder relevance.

    The cross-encoder reads (query, chunk) together, so it can separate
    sibling notes that share vocabulary — exactly what first-stage
    retrieval can't do. No cross-encoder (still loading, failed, disabled)
    or nothing to rank → the input order stands.
    """
    if cross_encoder is None or not candidates:
        return candidates[:k]
    pairs = [(query_text, c["chunk"]) for c in candidates]
    scores = cross_encoder.predict(pairs)
    order = sorted(range(len(candidates)), key=lambda i: float(scores[i]), reverse=True)
    return [{**candidates[i], "rerank_score": float(scores[i])} for i in order[:k]]


def retrieve_hybrid(query_text, *, model, collection, lexical=None,
                    cross_encoder=None, scope="notes", k=TOP_K):
    """Vector + BM25 fused with RRF, optionally reranked by a cross-encoder.

    Falls back gracefully at each stage: no lexical index → vector-only;
    no cross-encoder → fused order. Without a cross-encoder the behavior
    is identical to the pre-reranker version.
    """
    vector = retrieve(query_text, model=model, collection=collection,
                      scope=scope, k=HYBRID_DEPTH)
    if lexical is None or len(lexical) == 0:
        fused = vector
    else:
        keyword = lexical.search(query_text, scope=scope, k=HYBRID_DEPTH)
        fused = rrf_fuse([vector, keyword], k=RERANK_DEPTH)
    if cross_encoder is not None:
        return rerank(query_text, fused[:RERANK_DEPTH], cross_encoder=cross_encoder, k=k)
    return fused[:k]
