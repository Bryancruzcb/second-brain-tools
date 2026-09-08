from fastapi.testclient import TestClient

import main


def test_lexical_refresh_rebuilds_when_collection_ready(monkeypatch):
    calls = {"n": 0}

    def fake_build():
        calls["n"] += 1
        main.lexical_index = type("L", (), {"__len__": lambda self: 3})()

    monkeypatch.setattr(main, "chroma_collection", object())
    monkeypatch.setattr(main, "_build_lexical_index", fake_build)
    client = TestClient(main.app)
    resp = client.post("/api/lexical/refresh")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "chunks": 3}
    assert calls["n"] == 1


def test_lexical_refresh_503_without_collection(monkeypatch):
    monkeypatch.setattr(main, "chroma_collection", None)
    client = TestClient(main.app)
    assert client.post("/api/lexical/refresh").status_code == 503
