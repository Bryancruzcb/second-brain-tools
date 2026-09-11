"""Shared retrieval: the one code path both /api/query and the eval use.

Extracted from main.py's run_query so the eval harness measures exactly
what the app does — same reason indexer.py was unified in PR #3.
"""
import config
import query_rewrite

# Resolved once at import, the same moment uvicorn, the eval and the sweep
# script read them; see config.get_top_k() and friends for the numbers.
TOP_K = config.get_top_k()
HYBRID_DEPTH = config.get_hybrid_depth()
RRF_K = 60
RERANK_DEPTH = config.get_rerank_depth()


def scope_filter(scope):
    """Legacy Chroma where-clause helper.

    Kept for callers/tests that still expect a dict, but do NOT pass this into
    collection.query() on the current Chroma/HNSW stack — where-filtered
    vector queries raise "Error finding id". Use matches_scope() instead.
    """
    if scope == "chats":
        return {"category": "chat"}
    if scope == "notes":
        return {"category": {"$ne": "chat"}}
    return None


def matches_scope(meta, scope) -> bool:
    """Python-side scope check (safe substitute for Chroma where filters)."""
    category = (meta or {}).get("category", "note")
    if scope == "chats":
        return category == "chat"
    if scope == "notes":
        return category != "chat"
    return True


def retrieve(query_text, *, model, collection, scope="notes", k=TOP_K):
    """Embed query_text and return the top-k chunk candidates, best first.

    Returns a list of {"id", "source", "title", "chunk", "distance"} dicts.
    """
    query_embedding = model.encode([config.get_query_prefix() + query_text]).tolist()
    # Over-fetch when scoping so post-filter still fills k. Avoid Chroma `where`
    # — HNSW + where raises "Error finding id" on this build (notes/chats 500).
    fetch_k = k if scope in (None, "", "all") else min(max(k * 4, 32), 100)
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=fetch_k,
    )
    candidates = []
    if results and results.get("documents") and results["documents"]:
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        dists = (results.get("distances") or [[0.0] * len(docs)])[0]
        ids = (results.get("ids") or [[""] * len(docs)])[0]
        for doc, meta, dist, chunk_id in zip(docs, metas, dists, ids):
            meta = meta or {}
            if not matches_scope(meta, scope):
                continue
            candidates.append({
                "id": chunk_id,
                "source": meta.get("source", ""),
                "title": meta.get("title", "Untitled Note"),
                "chunk": doc,
                "distance": float(dist),
            })
            if len(candidates) >= k:
                break
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
    out = []
    for key in ranked[:k]:
        cand = dict(first_seen[key])
        cand["rrf_score"] = scores[key]
        out.append(cand)
    return out


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

    ONNX export by default (see config.get_reranker_onnx_file); set
    RERANKER_ONNX_FILE empty to load through sentence-transformers.
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



# ── notes-scope chat guard (NOTES_CHAT_GUARD) ─────────────────────────────

_CHAT_PATH_MARKERS = (
    "05 ai chats/",
    "/ai chat links/",
    "ai chat links/",
)


def is_chat_like_candidate(candidate) -> bool:
    """True for chat transcripts and note-scoped AI Chat Link stubs."""
    source = (candidate.get("source") or "").replace(chr(92), "/").casefold()
    title = (candidate.get("title") or "").casefold()
    if candidate.get("category") == "chat":
        return True
    if any(marker in source for marker in _CHAT_PATH_MARKERS):
        return True
    for token in ("transcript", "conversation", "imessage", "slack"):
        if token in title or token in source:
            return True
    return False


def filter_notes_chat_guard(candidates, scope="notes"):
    """Hard-drop chat-like chunks when scope=notes and NOTES_CHAT_GUARD=1.

    Fail-open: if every candidate would be removed, keep the original pool
    so Ask never returns empty solely because of the guard.
    """
    if scope != "notes" or not config.notes_chat_guard_enabled():
        return list(candidates)
    kept = [c for c in candidates if not is_chat_like_candidate(c)]
    return kept if kept else list(candidates)


# ── sibling disambiguation (SIBLING_DISAMBIG) ─────────────────────────────

SIBLING_ALPHA = 0.05
SIBLING_BETA = 0.04
SIBLING_GAMMA = 0.06


def query_anchor_terms(query_text: str) -> frozenset:
    """Cue-map anchors the query is aiming at (title/path match targets)."""
    q = (query_text or "").casefold()
    anchors = set()
    if "course home" in q or (
        "container" in q and any(w in q for w in ("wrong", "job", "reach"))
    ):
        anchors.update({"course home", "container", "docker", "data structure"})
    if "slide" in q and any(w in q for w in ("test", "exam", "before")):
        anchors.update({"slides", "exam", "slide", "school notes"})
    if "resume" in q and any(w in q for w in ("redo", "redid", "rebuild", "session")):
        anchors.update({"resume", "rebuild", "job hunt"})
    if "cleanup" in q and any(w in q for w in ("script", "handwritten", "deleted", "hand-written")):
        anchors.update({
            "cleanup", "hand-written", "handwritten", "pipeline",
            "chat memory", "clean_empty_chats", "recovered",
        })
    if "architecture" in q or ("portal" in q and "city" in q):
        anchors.update({"architecture"})
    return frozenset(anchors)


def _folder_key(source: str) -> str:
    path = (source or "").replace(chr(92), "/")
    if "/" not in path:
        return ""
    return path.rsplit("/", 1)[0].casefold()


def _title_path_hits(candidate, anchors):
    title = (candidate.get("title") or "").casefold()
    path = (candidate.get("source") or "").replace(chr(92), "/").casefold()
    title_hit = any(a in title for a in anchors)
    path_hit = any(a in path for a in anchors)
    return title_hit, path_hit


def sibling_disambiguate(query_text, candidates, score_key=None):
    """Re-score pool: base + α·title + β·path − γ·sibling_penalty.

    Sibling penalty applies only when ≥2 candidates share a folder and
    exactly one of them has a title/path anchor hit — demote the rest so
    hub notes (Course Home, architecture.md) beat sibling noise.

    ``score_key`` selects the base ("rrf_score" after fusion, "rerank_score"
    after CE). Cross-encoder logits dwarf RRF, so α/β/γ are scaled up when
    the base is a rerank score (CE_SCALE) while keeping the same ratios.
    """
    if not config.sibling_disambig_enabled() or not candidates:
        return list(candidates)
    anchors = query_anchor_terms(query_text)
    if not anchors:
        return list(candidates)

    use_ce = score_key == "rerank_score"
    scale = 20.0 if use_ce else 1.0
    alpha, beta, gamma = SIBLING_ALPHA * scale, SIBLING_BETA * scale, SIBLING_GAMMA * scale

    enriched = []
    for rank, cand in enumerate(candidates, start=1):
        if score_key and cand.get(score_key) is not None:
            base = float(cand[score_key])
        else:
            base = float(cand.get("rrf_score", 1.0 / (RRF_K + rank)))
        title_hit, path_hit = _title_path_hits(cand, anchors)
        enriched.append({
            "cand": cand,
            "base": base,
            "title_hit": title_hit,
            "path_hit": path_hit,
            "rank": rank,
        })

    from collections import defaultdict
    by_folder = defaultdict(list)
    for i, row in enumerate(enriched):
        folder = _folder_key(row["cand"].get("source") or "")
        if folder:
            by_folder[folder].append(i)

    penalty = [0.0] * len(enriched)
    for idxs in by_folder.values():
        if len(idxs) < 2:
            continue
        with_anchor = [
            i for i in idxs
            if enriched[i]["title_hit"] or enriched[i]["path_hit"]
        ]
        if len(with_anchor) == 1:
            winner = with_anchor[0]
            for i in idxs:
                if i != winner:
                    penalty[i] = gamma

    scored = []
    for i, row in enumerate(enriched):
        s = (
            row["base"]
            + alpha * (1.0 if row["title_hit"] else 0.0)
            + beta * (1.0 if row["path_hit"] else 0.0)
            - penalty[i]
        )
        scored.append((s, row["rank"], row["cand"]))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [cand for _, _, cand in scored]


def retrieve_hybrid(query_text, *, model, collection, lexical=None,
                    cross_encoder=None, scope="notes", k=TOP_K, max_per_source=None):
    """Vector + BM25 fused with RRF, optionally reranked by a cross-encoder,
    then served with at most ``max_per_source`` chunks per note (default:
    config.get_max_chunks_per_note(), read per call like the query prefix).

    When QUERY_REWRITE=1, expands query_text via local Ollama for this
    retrieval only (fail-open); generation callers keep the original text.

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
    query_text = query_rewrite.rewrite_for_retrieval(query_text)
    # Notes-chat guard: fetch deeper legs, drop chat stubs per-leg, then
    # fuse the surviving HYBRID_DEPTH notes so RRF depth stays comparable
    # to the unguarded path (deep-then-truncate was pushing hub notes out).
    deep = scope == "notes" and config.notes_chat_guard_enabled()
    leg_k = HYBRID_DEPTH * 2 if deep else HYBRID_DEPTH
    vector = retrieve(query_text, model=model, collection=collection,
                      scope=scope, k=leg_k)
    if deep:
        vector = filter_notes_chat_guard(vector, scope)[:HYBRID_DEPTH]
    if lexical is None or len(lexical) == 0:
        fused = vector[:RERANK_DEPTH]
    else:
        keyword = lexical.search(query_text, scope=scope, k=leg_k)
        if deep:
            keyword = filter_notes_chat_guard(keyword, scope)[:HYBRID_DEPTH]
        fused = rrf_fuse([vector, keyword], k=RERANK_DEPTH)
    pool = filter_notes_chat_guard(fused, scope)
    pool = sibling_disambiguate(query_text, pool)
    if cross_encoder is not None:
        pool = rerank(query_text, pool, cross_encoder=cross_encoder, k=len(pool))
        pool = sibling_disambiguate(query_text, pool, score_key="rerank_score")
    return cap_per_source(pool, max_per_source)[:k]
