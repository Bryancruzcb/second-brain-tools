from fastapi.testclient import TestClient

import main
from tests.test_retrieval import CANNED, FakeCollection, FakeLexical, FakeModel


def test_query_serves_lexical_only_candidates_without_distance(monkeypatch):
    coll = FakeCollection(CANNED)
    lex = FakeLexical([
        {"id": "id_l", "source": "l.md", "title": "Lex", "chunk": "lexical hit", "score": 3.0},
    ])
    monkeypatch.setattr(main, "model", FakeModel())
    monkeypatch.setattr(main, "chroma_collection", coll)
    monkeypatch.setattr(main, "lexical_index", lex)
    monkeypatch.setattr(main, "ollama_chat", lambda messages, max_tokens: "canned answer")
    client = TestClient(main.app)

    resp = client.post("/api/query", json={"query": "x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "canned answer"
    by_title = {s["title"]: s for s in body["sources"]}
    # A lexical-only candidate carries "score", not "distance": formatting it
    # with c["distance"] raises KeyError and the handler turns that into a 500.
    assert by_title["Lex"]["distance"] == 0.0
    # ...and the vector leg is still in the fused result, so this pins fusion
    # rather than a lexical-only response.
    assert by_title["A"]["distance"] == 0.1
