from fastapi.testclient import TestClient

import main
import retrieval
from tests.test_retrieval import FakeModel, FakeCollection

CANNED = {
    "ids": [["id_a", "id_a2", "id_b"]],
    "documents": [["alpha chunk one", "alpha chunk two", "beta chunk"]],
    "metadatas": [[
        {"source": "a.md", "title": "Alpha"},
        {"source": "a.md", "title": "Alpha"},
        {"source": "b.md", "title": "Beta"},
    ]],
    "distances": [[0.1, 0.2, 0.3]],
}

# Same rows tagged as chat transcripts, for the scope="chats" path: scope is
# now applied in Python from the category metadata, not by a Chroma where.
CHATS_CANNED = {
    **CANNED,
    "metadatas": [[{**m, "category": "chat"} for m in CANNED["metadatas"][0]]],
}


def test_search_dedupes_titles_and_keeps_shape(monkeypatch):
    coll = FakeCollection(CHATS_CANNED)
    monkeypatch.setattr(main, "model", FakeModel())
    monkeypatch.setattr(main, "chroma_collection", coll)
    monkeypatch.setattr(main, "lexical_index", None)  # pin the vector-only fallback
    client = TestClient(main.app)

    resp = client.get("/api/search", params={"q": "alpha", "scope": "chats"})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results == [
        {"title": "Alpha", "id": "a.md", "snippet": "alpha chunk one"},
        {"title": "Beta", "id": "b.md", "snippet": "beta chunk"},
    ]
    # The vector leg over-fetches without a Chroma where (HNSW + where raises
    # "Error finding id") and filters by category in Python afterward.
    assert coll.last_kwargs["n_results"] == min(max(retrieval.HYBRID_DEPTH * 4, 32), 100)
    assert "where" not in coll.last_kwargs


def test_search_empty_query_returns_empty(monkeypatch):
    monkeypatch.setattr(main, "model", FakeModel())
    monkeypatch.setattr(main, "chroma_collection", FakeCollection(CANNED))
    monkeypatch.setattr(main, "lexical_index", None)
    client = TestClient(main.app)
    assert client.get("/api/search", params={"q": "  "}).json() == {"results": []}


def test_search_uses_lexical_leg_when_available(monkeypatch):
    from tests.test_retrieval import FakeLexical
    coll = FakeCollection(CANNED)
    lex = FakeLexical([
        {"id": "id_l", "source": "l.md", "title": "Lex", "chunk": "lexical hit", "score": 3.0},
    ])
    monkeypatch.setattr(main, "model", FakeModel())
    monkeypatch.setattr(main, "chroma_collection", coll)
    monkeypatch.setattr(main, "lexical_index", lex)
    client = TestClient(main.app)
    titles = [r["title"] for r in client.get("/api/search", params={"q": "x"}).json()["results"]]
    assert "Lex" in titles
    # NOTES_CHAT_GUARD (default ON) deep-fetches 2x HYBRID_DEPTH on notes scope.
    assert lex.last_args[2] == retrieval.HYBRID_DEPTH * 2


def test_search_reranks_and_hides_rerank_score(monkeypatch):
    from tests.fakes import OverlapCrossEncoder
    coll = FakeCollection(CANNED)
    monkeypatch.setattr(main, "model", FakeModel())
    monkeypatch.setattr(main, "chroma_collection", coll)
    monkeypatch.setattr(main, "lexical_index", None)
    monkeypatch.setattr(main, "cross_encoder", OverlapCrossEncoder())
    client = TestClient(main.app)

    results = client.get("/api/search", params={"q": "beta chunk"}).json()["results"]
    assert results[0]["title"] == "Beta"          # promoted over Alpha by the reranker
    assert set(results[0].keys()) == {"title", "id", "snippet"}  # rerank_score not leaked


def test_search_passes_configured_top_k(monkeypatch):
    """ /api/search must use the same TOP_K as Ask, not a hardcoded mismatch. """
    seen = {}

    def fake_hybrid(q, **kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(main, "model", FakeModel())
    monkeypatch.setattr(main, "chroma_collection", FakeCollection(CANNED))
    monkeypatch.setattr(main, "lexical_index", None)
    monkeypatch.setattr(retrieval, "retrieve_hybrid", fake_hybrid)
    client = TestClient(main.app)
    assert client.get("/api/search", params={"q": "x"}).json() == {"results": []}
    assert seen.get("k") == retrieval.TOP_K
