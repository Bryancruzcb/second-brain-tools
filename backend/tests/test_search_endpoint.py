from fastapi.testclient import TestClient

import main
from tests.test_retrieval import FakeModel, FakeCollection

CANNED = {
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
    client = TestClient(main.app)

    resp = client.get("/api/search", params={"q": "alpha", "scope": "chats"})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results == [
        {"title": "Alpha", "id": "a.md", "snippet": "alpha chunk one"},
        {"title": "Beta", "id": "b.md", "snippet": "beta chunk"},
    ]
    assert coll.last_kwargs["n_results"] == 6
    assert coll.last_kwargs["where"] == {"category": "chat"}


def test_search_empty_query_returns_empty(monkeypatch):
    monkeypatch.setattr(main, "model", FakeModel())
    monkeypatch.setattr(main, "chroma_collection", FakeCollection(CANNED))
    client = TestClient(main.app)
    assert client.get("/api/search", params={"q": "  "}).json() == {"results": []}
