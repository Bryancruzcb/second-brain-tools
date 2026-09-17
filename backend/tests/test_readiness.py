"""/api/ready has two contracts: a body for clients, a status line for kubelet."""
from fastapi.testclient import TestClient

import main


def test_strict_readiness_refuses_while_cold(monkeypatch):
    """?strict=1 is the probe contract: a status line, not a body to parse."""
    monkeypatch.setattr(main, "model", None)
    resp = TestClient(main.app).get("/api/ready", params={"strict": 1})
    assert resp.status_code == 503
    assert resp.json()["detail"]["components"]["embedding_model"] is False


def test_strict_readiness_passes_once_loaded(monkeypatch):
    for name in ("model", "chroma_collection", "lexical_index", "cross_encoder"):
        monkeypatch.setattr(main, name, object())
    resp = TestClient(main.app).get("/api/ready", params={"strict": 1})
    assert resp.status_code == 200
    assert resp.json()["ready"] is True


def test_plain_readiness_still_answers_200_while_cold(monkeypatch):
    """The frontend says "warming up" from this body; an error would say offline."""
    monkeypatch.setattr(main, "model", None)
    resp = TestClient(main.app).get("/api/ready")
    assert resp.status_code == 200
    assert resp.json()["ready"] is False
