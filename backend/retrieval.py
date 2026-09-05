"""Shared retrieval: the one code path both /api/query and the eval use.

Extracted from main.py's run_query so the eval harness measures exactly
what the app does — same reason indexer.py was unified in PR #3.
"""
import config

# Resolved once at import, the same moment uvicorn, the eval and the sweep
# script read them; see config.get_top_k() and friends for the numbers.
TOP_K = config.get_top_k()
HYBRID_DEPTH = config.get_hybrid_depth()
RRF_K = 60
RERANK_DEPTH = config.get_rerank_depth()


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
    query_embedding = model.encode([config.get_query_prefix() + query_text]).tolist()
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


class OnnxCrossEncoder:
    """A cross-encoder served from an ONNX export: predict(pairs) -> scores.

    onnxruntime is already a chromadb dependency, so a quantised export of
    the reranker costs no new package. Tokenisation mirrors
    sentence_transformers.CrossEncoder (pair input, padding, longest-first
    truncation at max_length), and rerank() only ever calls predict().
    """

    def __init__(self, session, tokenizer, max_length=512):
        self.session = session
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.input_names = [i.name for i in session.get_inputs()]

    @classmethod
    def from_hub(cls, model_name, onnx_file, max_length=512):
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from transformers import AutoTokenizer
        path = hf_hub_download(model_name, onnx_file)
        session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        return cls(session, AutoTokenizer.from_pretrained(model_name), max_length)

    def predict(self, pairs, batch_size=32, **_):
        import numpy as np
        scores = []
        for i in range(0, len(pairs), batch_size):
            batch = pairs[i:i + batch_size]
            enc = self.tokenizer([q for q, _ in batch], [d for _, d in batch], padding=True,
                                 truncation=True, max_length=self.max_length, return_tensors="np")
            ids = np.asarray(enc["input_ids"], dtype=np.int64)
            feed = {}
            for name in self.input_names:
                feed[name] = np.asarray(enc[name], dtype=np.int64) if name in enc else np.zeros_like(ids)
            logits = np.asarray(self.session.run(None, feed)[0])
            scores.extend(float(x) for x in (logits[:, 0] if logits.ndim == 2 else logits.reshape(-1)))
        return scores


def load_reranker(name=None):
    """The configured cross-encoder, shared by the API and the eval.

    sentence-transformers by default; an ONNX export of the same repo when
    RERANKER_ONNX_FILE is set (see config.get_reranker_onnx_file).
    """
    name = name or config.get_reranker_model()
    onnx_file = config.get_reranker_onnx_file()
    if onnx_file:
        return OnnxCrossEncoder.from_hub(name, onnx_file, max_length=512)
    from sentence_transformers import CrossEncoder
    return CrossEncoder(name)


def cap_per_source(candidates, cap):
    """Keep at most ``cap`` chunks per note, preserving order; 0 means no cap.

    Long generic notes put several chunks in the reranked top-k, so without
    a cap a bigger k shows Qwen more of the same notes. Measured 2026-09-04
    at depth 30: served hit-rate 80.0% at every k from 4 to 10 uncapped,
    80.0 / 82.5 / 85.0% at k=4 / 6 / 8 with one chunk per note.
    """
    if cap <= 0:
        return list(candidates)
    seen = {}
    out = []
    for c in candidates:
        n = seen.get(c["source"], 0)
        if n < cap:
            out.append(c)
            seen[c["source"]] = n + 1
    return out


def retrieve_hybrid(query_text, *, model, collection, lexical=None,
                    cross_encoder=None, scope="notes", k=TOP_K, max_per_source=None):
    """Vector + BM25 fused with RRF, optionally reranked by a cross-encoder,
    then served with at most ``max_per_source`` chunks per note (default:
    config.get_max_chunks_per_note(), read per call like the query prefix).

    Falls back gracefully at each stage: no lexical index → vector-only;
    no cross-encoder → fused order. The whole RERANK_DEPTH pool is ranked
    before the cap and the cut to k, so the cap admits the next-best note
    rather than truncating to fewer than k results whenever the pool has
    enough distinct notes.

    Caveat: on the fused path a caller asking for k above RERANK_DEPTH gets
    at most RERANK_DEPTH results.
    """
    if max_per_source is None:
        max_per_source = config.get_max_chunks_per_note()
    vector = retrieve(query_text, model=model, collection=collection,
                      scope=scope, k=HYBRID_DEPTH)
    if lexical is None or len(lexical) == 0:
        fused = vector
    else:
        keyword = lexical.search(query_text, scope=scope, k=HYBRID_DEPTH)
        fused = rrf_fuse([vector, keyword], k=RERANK_DEPTH)
    pool = fused[:RERANK_DEPTH]
    if cross_encoder is not None:
        pool = rerank(query_text, pool, cross_encoder=cross_encoder, k=len(pool))
    return cap_per_source(pool, max_per_source)[:k]
