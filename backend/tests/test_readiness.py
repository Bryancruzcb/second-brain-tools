"""/api/ready has two contracts: a body for clients, a status line for kubelet."""
from fastapi.testclient import TestClient

import main


def test_strict_readiness_refuses_while_cold(monkeypatch):
    """?strict=1 is the probe contract: a status line, not a body to parse."""
    monkeypatch.setattr(main, "model", None)
    resp = TestClient(main.app).get("/api/ready", params={"strict": 1})
    assert resp.status_code == 503
    assert resp.json()["detail"]["components"]["embedding_model"] is False


class _Collection:
    def __init__(self, chunks):
        self.chunks = chunks

    def count(self):
        if isinstance(self.chunks, Exception):
            raise self.chunks
        return self.chunks


def _loaded(monkeypatch, collection):
    for name in ("model", "lexical_index", "cross_encoder"):
        monkeypatch.setattr(main, name, object())
    monkeypatch.setattr(main, "chroma_collection", collection)
    # No real store behind these fakes, so a reopen finds nothing new.
    monkeypatch.setattr(main, "ensure_chroma_fresh", lambda: False)


def test_strict_readiness_passes_once_loaded(monkeypatch):
    _loaded(monkeypatch, _Collection(1200))
    resp = TestClient(main.app).get("/api/ready", params={"strict": 1})
    assert resp.status_code == 200
    assert resp.json()["ready"] is True
    assert resp.json()["index_populated"] is True


def test_strict_readiness_refuses_an_empty_index(monkeypatch):
    """Staging's first pod loaded every model over an empty volume and went Ready."""
    _loaded(monkeypatch, _Collection(0))
    resp = TestClient(main.app).get("/api/ready", params={"strict": 1})
    assert resp.status_code == 503
    assert resp.json()["detail"]["index_populated"] is False


def test_strict_readiness_reopens_a_store_another_process_filled(monkeypatch):
    """On a fresh node only the probe can notice the indexer's writes: a pod
    that isn't Ready has no Service endpoints for the indexer's refresh call."""
    _loaded(monkeypatch, _Collection(0))
    reopened = []

    def fake_fresh():
        reopened.append(True)
        monkeypatch.setattr(main, "chroma_collection", _Collection(1200))
        return True

    monkeypatch.setattr(main, "ensure_chroma_fresh", fake_fresh)
    resp = TestClient(main.app).get("/api/ready", params={"strict": 1})
    assert resp.status_code == 200
    assert reopened == [True]


def test_plain_readiness_never_reopens_the_store(monkeypatch):
    """The frontend polls the plain endpoint; reopens stay on the probe."""
    _loaded(monkeypatch, _Collection(0))
    monkeypatch.setattr(main, "ensure_chroma_fresh", lambda: (_ for _ in ()).throw(AssertionError))
    assert TestClient(main.app).get("/api/ready").status_code == 200


def test_strict_readiness_refuses_while_the_store_cannot_count(monkeypatch):
    _loaded(monkeypatch, _Collection(RuntimeError("store is being rewritten")))
    resp = TestClient(main.app).get("/api/ready", params={"strict": 1})
    assert resp.status_code == 503


def test_plain_readiness_keeps_an_empty_index_ready(monkeypatch):
    """Clients read ready=false as "still loading"; an empty vault is not that."""
    _loaded(monkeypatch, _Collection(0))
    resp = TestClient(main.app).get("/api/ready")
    assert resp.status_code == 200
    assert resp.json()["ready"] is True
    assert resp.json()["index_populated"] is False


def test_plain_readiness_still_answers_200_while_cold(monkeypatch):
    """The frontend says "warming up" from this body; an error would say offline."""
    monkeypatch.setattr(main, "model", None)
    resp = TestClient(main.app).get("/api/ready")
    assert resp.status_code == 200
    assert resp.json()["ready"] is False
