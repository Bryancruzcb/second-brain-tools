import retrieval


class FakeModel:
    def encode(self, texts):
        import numpy as np
        return np.zeros((len(texts), 4), dtype=np.float32)


class FakeCollection:
    """Records query kwargs and returns a canned Chroma-shaped result."""
    def __init__(self, result):
        self.result = result
        self.last_kwargs = None

    def query(self, **kwargs):
        self.last_kwargs = kwargs
        return self.result


CANNED = {
    "ids": [["id_a", "id_b"]],
    "documents": [["chunk one text", "chunk two text"]],
    "metadatas": [[{"source": "a.md", "title": "A"}, {"source": "b.md", "title": "B"}]],
    "distances": [[0.1, 0.4]],
}


def test_retrieve_parses_chroma_results_into_candidates():
    coll = FakeCollection(CANNED)
    out = retrieval.retrieve("q", model=FakeModel(), collection=coll)
    assert out == [
        {"id": "id_a", "source": "a.md", "title": "A", "chunk": "chunk one text", "distance": 0.1},
        {"id": "id_b", "source": "b.md", "title": "B", "chunk": "chunk two text", "distance": 0.4},
    ]


def test_retrieve_passes_k_and_scope_filter():
    coll = FakeCollection(CANNED)
    retrieval.retrieve("q", model=FakeModel(), collection=coll, scope="chats", k=7)
    assert coll.last_kwargs["n_results"] == 7
    assert coll.last_kwargs["where"] == {"category": "chat"}


def test_retrieve_handles_empty_results():
    coll = FakeCollection({"documents": [[]], "metadatas": [[]], "distances": [[]]})
    assert retrieval.retrieve("q", model=FakeModel(), collection=coll) == []


def test_scope_filters():
    assert retrieval.scope_filter("chats") == {"category": "chat"}
    assert retrieval.scope_filter("notes") == {"category": {"$ne": "chat"}}
    assert retrieval.scope_filter("all") is None


def test_missing_metadata_gets_defaults():
    coll = FakeCollection({
        "documents": [["text"]],
        "metadatas": [[None]],
        "distances": [[0.2]],
    })
    out = retrieval.retrieve("q", model=FakeModel(), collection=coll)
    assert out[0]["source"] == ""
    assert out[0]["title"] == "Untitled Note"


def test_retrieve_tolerates_missing_ids_key():
    coll = FakeCollection({
        "documents": [["text"]],
        "metadatas": [[{"source": "a.md", "title": "A"}]],
        "distances": [[0.2]],
    })
    out = retrieval.retrieve("q", model=FakeModel(), collection=coll)
    assert out[0]["id"] == ""


def _cand(cid, source="s.md"):
    return {"id": cid, "source": source, "title": "T", "chunk": f"chunk {cid}", "distance": 0.1}


def test_rrf_item_in_both_lists_wins():
    a, b, c = _cand("a"), _cand("b"), _cand("c")
    fused = retrieval.rrf_fuse([[a, b], [c, a]], k=3)
    assert fused[0]["id"] == "a"  # 1/(60+1) + 1/(60+2) beats any single entry


def test_rrf_scores_by_rank_position():
    a, b = _cand("a"), _cand("b")
    fused = retrieval.rrf_fuse([[a, b], [b, a]], k=2)
    # both sum to 1/61 + 1/62 — tie; first-inserted (a, from list one) wins
    assert [c["id"] for c in fused] == ["a", "b"]


def test_rrf_truncates_to_k():
    lst = [_cand(str(i)) for i in range(6)]
    assert len(retrieval.rrf_fuse([lst], k=4)) == 4


def test_rrf_falls_back_to_source_chunk_identity_when_id_empty():
    x1 = {"id": "", "source": "x.md", "title": "X", "chunk": "same text", "distance": 0.1}
    x2 = {"id": "", "source": "x.md", "title": "X", "chunk": "same text", "score": 2.0}
    fused = retrieval.rrf_fuse([[x1], [x2]], k=2)
    assert len(fused) == 1  # same chunk, fused despite different score keys


class FakeLexical:
    def __init__(self, results):
        self.results = results
        self.last_args = None

    def __len__(self):
        return len(self.results)

    def search(self, query_text, scope="notes", k=10):
        self.last_args = (query_text, scope, k)
        return self.results[:k]


def test_hybrid_falls_back_to_vector_only_without_lexical():
    coll = FakeCollection(CANNED)
    out = retrieval.retrieve_hybrid("q", model=FakeModel(), collection=coll, lexical=None, k=2)
    assert [c["id"] for c in out] == ["id_a", "id_b"]
    assert coll.last_kwargs["n_results"] == retrieval.HYBRID_DEPTH


def test_hybrid_fuses_vector_and_lexical():
    coll = FakeCollection(CANNED)
    lex = FakeLexical([_cand("id_b"), _cand("id_z")])
    out = retrieval.retrieve_hybrid("q", model=FakeModel(), collection=coll, lexical=lex, scope="chats", k=2)
    assert out[0]["id"] == "id_b"  # in both lists
    assert lex.last_args == ("q", "chats", retrieval.HYBRID_DEPTH)


from tests.fakes import OverlapCrossEncoder


def _chunked(cid, text):
    return {"id": cid, "source": f"{cid}.md", "title": cid, "chunk": text, "distance": 0.1}


def test_rerank_reorders_by_cross_encoder_score():
    cands = [_chunked("a", "nothing relevant here"), _chunked("b", "exact match words")]
    out = retrieval.rerank("exact match words", cands, cross_encoder=OverlapCrossEncoder(), k=2)
    assert [c["id"] for c in out] == ["b", "a"]
    assert out[0]["rerank_score"] == 3.0


def test_rerank_truncates_to_k():
    cands = [_chunked(str(i), f"text {i}") for i in range(6)]
    assert len(retrieval.rerank("text", cands, cross_encoder=OverlapCrossEncoder(), k=4)) == 4


def test_rerank_ties_keep_fused_order():
    cands = [_chunked("first", "same words"), _chunked("second", "same words")]
    out = retrieval.rerank("same words", cands, cross_encoder=OverlapCrossEncoder(), k=2)
    assert [c["id"] for c in out] == ["first", "second"]


def test_rerank_none_cross_encoder_falls_back():
    cands = [_chunked("a", "x"), _chunked("b", "y")]
    assert retrieval.rerank("q", cands, cross_encoder=None, k=1) == cands[:1]


def test_rerank_does_not_mutate_input():
    cands = [_chunked("a", "match me")]
    retrieval.rerank("match me", cands, cross_encoder=OverlapCrossEncoder(), k=1)
    assert "rerank_score" not in cands[0]


def test_hybrid_reranks_fused_pool():
    coll = FakeCollection(CANNED)
    lex = FakeLexical([
        {"id": "id_kw", "source": "kw.md", "title": "KW", "chunk": "totally specific answer tokens", "score": 5.0},
    ])
    out = retrieval.retrieve_hybrid(
        "totally specific answer tokens", model=FakeModel(), collection=coll,
        lexical=lex, cross_encoder=OverlapCrossEncoder(), k=1,
    )
    # RRF alone would rank a vector candidate first (rank 1 in the bigger
    # list); the cross-encoder must promote the keyword hit that actually
    # matches the query.
    assert out[0]["id"] == "id_kw"


def test_hybrid_vector_fallback_still_reranks():
    coll = FakeCollection(CANNED)
    out = retrieval.retrieve_hybrid(
        "chunk two text", model=FakeModel(), collection=coll,
        lexical=None, cross_encoder=OverlapCrossEncoder(), k=1,
    )
    assert out[0]["id"] == "id_b"  # promoted over id_a (distance order) by overlap


def test_hybrid_without_cross_encoder_unchanged():
    coll = FakeCollection(CANNED)
    out = retrieval.retrieve_hybrid("q", model=FakeModel(), collection=coll, lexical=None, k=2)
    assert [c["id"] for c in out] == ["id_a", "id_b"]
    assert all("rerank_score" not in c for c in out)


class RecordingModel:
    def __init__(self):
        self.seen = []

    def encode(self, texts):
        import numpy as np
        self.seen.extend(texts)
        return np.zeros((len(texts), 4), dtype=np.float32)


def test_query_prefix_applies_to_vector_encode_only(monkeypatch):
    monkeypatch.setenv("EMBEDDING_QUERY_PREFIX", "query: ")
    rec = RecordingModel()
    lex = FakeLexical([
        {"id": "id_l", "source": "l.md", "title": "L", "chunk": "text", "score": 1.0},
    ])
    retrieval.retrieve_hybrid("find me", model=rec, collection=FakeCollection(CANNED), lexical=lex, k=2)
    assert rec.seen == ["query: find me"]          # vector leg sees the prefix
    assert lex.last_args[0] == "find me"           # BM25 leg does not


# ── per-note chunk cap ────────────────────────────────────────────────────

MAGNET = {
    "ids": [["a1", "a2", "a3", "b1"]],
    "documents": [["magnet one", "magnet two", "magnet three", "other"]],
    "metadatas": [[{"source": "a.md", "title": "A"}] * 3 + [{"source": "b.md", "title": "B"}]],
    "distances": [[0.1, 0.2, 0.3, 0.4]],
}


def test_cap_per_source_keeps_order_and_limits_chunks_per_note():
    ranked = [_cand("b1", "b.md"), _cand("b2", "b.md"), _cand("a1", "a.md"),
              _cand("b3", "b.md"), _cand("c1", "c.md")]
    assert [c["id"] for c in retrieval.cap_per_source(ranked, 1)] == ["b1", "a1", "c1"]
    assert [c["id"] for c in retrieval.cap_per_source(ranked, 2)] == ["b1", "b2", "a1", "c1"]
    assert retrieval.cap_per_source(ranked, 0) == ranked  # 0 means no cap


def test_hybrid_serves_at_most_one_chunk_per_note_by_default(monkeypatch):
    monkeypatch.delenv("MAX_CHUNKS_PER_NOTE", raising=False)
    out = retrieval.retrieve_hybrid("q", model=FakeModel(), collection=FakeCollection(MAGNET), k=2)
    assert [c["id"] for c in out] == ["a1", "b1"]  # a2/a3 skipped, b.md reaches the list


def test_hybrid_cap_applies_after_reranking(monkeypatch):
    monkeypatch.delenv("MAX_CHUNKS_PER_NOTE", raising=False)
    out = retrieval.retrieve_hybrid(
        "other", model=FakeModel(), collection=FakeCollection(MAGNET),
        cross_encoder=OverlapCrossEncoder(), k=3,
    )
    # The reranker promotes b1 ("other" overlaps); the cap then admits one
    # a.md chunk, in reranked order, so the list stops at two notes even
    # though k asked for three chunks.
    assert [c["id"] for c in out] == ["b1", "a1"]


def test_hybrid_cap_is_env_configurable(monkeypatch):
    monkeypatch.setenv("MAX_CHUNKS_PER_NOTE", "0")
    out = retrieval.retrieve_hybrid("q", model=FakeModel(), collection=FakeCollection(MAGNET), k=3)
    assert [c["id"] for c in out] == ["a1", "a2", "a3"]
    monkeypatch.setenv("MAX_CHUNKS_PER_NOTE", "2")
    out = retrieval.retrieve_hybrid("q", model=FakeModel(), collection=FakeCollection(MAGNET), k=3)
    assert [c["id"] for c in out] == ["a1", "a2", "b1"]
