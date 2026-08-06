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


def test_search_dedupes_titles_and_keeps_shape(monkeypatch):
    coll = FakeCollection(CANNED)
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
    # The vector leg over-retrieves to fusion depth and truncates afterward,
    # so the kwarg changes while the response above stays identical.
    assert coll.last_kwargs["n_results"] == retrieval.HYBRID_DEPTH
    assert coll.last_kwargs["where"] == {"category": "chat"}


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
    assert lex.last_args[2] == 20  # HYBRID_DEPTH reaches the lexical leg
