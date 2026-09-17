"""READ_ONLY turns every write route into a 403.

The cloud pods run with the flag set, so this file is the contract the
deployed image is held to: the five write routes refuse, reads keep
answering, and nothing changes on a desktop that leaves the flag unset.
"""
import pytest
from fastapi.testclient import TestClient

import config
import main

# path, a body the route would accept if it were writable
WRITE_ROUTES = [
    ("/api/health/scan", None),
    ("/api/index", None),
    ("/api/note/create", {"title": "Cloud Note", "content": "body"}),
    ("/api/note/Some Note.md", {"content": "body"}),
    ("/api/clip", {"title": "T", "content": "c", "url": "https://example.com"}),
]


@pytest.mark.parametrize("path,body", WRITE_ROUTES, ids=lambda v: v if isinstance(v, str) else "")
def test_write_route_is_refused(monkeypatch, path, body):
    monkeypatch.setenv("READ_ONLY", "1")
    resp = TestClient(main.app).post(path, json=body)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Read-only deployment: writes are disabled."


def test_refusal_beats_body_validation(monkeypatch):
    """A write with a bad body still 403s, never 422.

    The deploy smoke test asserts 403 on one write request. If body
    validation ran first, that check would pass against a *writable* pod
    the moment the smoke payload drifted.
    """
    monkeypatch.setenv("READ_ONLY", "1")
    resp = TestClient(main.app).post("/api/note/create", json={"not": "a title"})
    assert resp.status_code == 403


def test_reads_still_answer_when_read_only(monkeypatch):
    monkeypatch.setenv("READ_ONLY", "1")
    client = TestClient(main.app)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/ready").status_code == 200


def test_write_works_when_flag_is_unset(monkeypatch, tmp_path):
    """Default off: the desktop keeps its editor and clipper."""
    monkeypatch.delenv("READ_ONLY", raising=False)
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path))
    resp = TestClient(main.app).post(
        "/api/note/create", json={"title": "Desktop Note", "content": "kept"}
    )
    assert resp.status_code == 200
    assert (tmp_path / "Desktop Note.md").read_text(encoding="utf-8") == "kept"


@pytest.mark.parametrize(
    "raw,expected",
    [("1", True), ("true", True), ("TRUE", True), ("yes", True), ("on", True),
     ("0", False), ("false", False), ("", False), ("maybe", False)],
)
def test_flag_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("READ_ONLY", raw)
    assert config.read_only() is expected


def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("READ_ONLY", raising=False)
    assert config.read_only() is False
