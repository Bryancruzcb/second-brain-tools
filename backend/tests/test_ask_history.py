"""Ask history: saved in the query path, listed, deleted, capped."""
import json

from fastapi.testclient import TestClient

import ask_history
import main
from tests.test_retrieval import CANNED, FakeCollection, FakeLexical, FakeModel


def _client(monkeypatch, answer="canned answer"):
    monkeypatch.setattr(main, "model", FakeModel())
    monkeypatch.setattr(main, "chroma_collection", FakeCollection(CANNED))
    monkeypatch.setattr(main, "lexical_index", FakeLexical([]))
    monkeypatch.setattr(main, "ollama_chat", lambda messages, max_tokens: answer)
    return TestClient(main.app)


def test_query_is_recorded_and_listed_newest_first(monkeypatch, tmp_path):
    client = _client(monkeypatch)
    assert client.get("/api/ask/history").json() == {"enabled": True, "entries": []}
    client.post("/api/query", json={"query": "  first question "})
    client.post("/api/query", json={"query": "second question", "scope": "all"})

    body = client.get("/api/ask/history").json()
    assert [e["question"] for e in body["entries"]] == ["second question", "first question"]
    entry = body["entries"][1]
    assert entry["answer"] == "canned answer"
    assert entry["scope"] == "notes"
    assert {s["title"] for s in entry["sources"]} == {"A", "B"}
    assert isinstance(entry["asked_at"], float) and entry["id"]
    assert client.get("/api/ask/history?limit=1").json()["entries"][0]["question"] == "second question"
    # Stored where ASK_HISTORY_PATH points (conftest: a tmp dir), as JSON.
    stored = json.loads((tmp_path / "ask_history.json").read_text(encoding="utf-8"))
    assert len(stored["entries"]) == 2


def test_failed_query_is_not_recorded(monkeypatch):
    client = _client(monkeypatch)

    def boom(messages, max_tokens):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(main, "ollama_chat", boom)
    assert client.post("/api/query", json={"query": "q"}).status_code == 500
    assert client.get("/api/ask/history").json()["entries"] == []


def test_delete_one_and_clear(monkeypatch):
    client = _client(monkeypatch)
    for q in ("a", "b", "c"):
        client.post("/api/query", json={"query": q})
    entries = client.get("/api/ask/history").json()["entries"]
    target = entries[1]["id"]
    assert client.delete(f"/api/ask/history/{target}").status_code == 200
    assert client.delete(f"/api/ask/history/{target}").status_code == 404
    assert [e["question"] for e in client.get("/api/ask/history").json()["entries"]] == ["c", "a"]
    assert client.delete("/api/ask/history").json() == {"status": "cleared", "removed": 2}
    assert client.get("/api/ask/history").json()["entries"] == []


def test_history_is_capped_oldest_dropped(monkeypatch):
    monkeypatch.setenv("ASK_HISTORY_MAX", "3")
    for i in range(5):
        ask_history.record(f"q{i}", "a", [], now=float(i))
    assert [e["question"] for e in ask_history.list_entries()] == ["q4", "q3", "q2"]


def test_snippets_are_trimmed(monkeypatch):
    entry = ask_history.record("q", "a", [{"title": "T", "source": "t.md", "snippet": "x" * 1000}])
    assert len(entry["sources"][0]["snippet"]) <= ask_history.SNIPPET_CHARS + 3


def test_corrupt_file_starts_fresh_and_record_never_raises(monkeypatch, tmp_path):
    path = tmp_path / "ask_history.json"
    path.write_text("{not json", encoding="utf-8")
    assert ask_history.list_entries() == []
    assert ask_history.record("q", "a", []) is not None
    monkeypatch.setenv("ASK_HISTORY_PATH", str(tmp_path))  # a directory: unwritable as a file
    assert ask_history.record("q", "a", []) is None


def test_read_only_deployment_neither_records_nor_serves(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setenv("READ_ONLY", "1")
    assert client.post("/api/query", json={"query": "q"}).status_code == 200
    assert client.get("/api/ask/history").json() == {"enabled": False, "entries": []}
    assert client.delete("/api/ask/history").status_code == 403


# ── both Ask endpoints, cache hits included ───────────────────────────────

from tests.test_query_stream import armed  # noqa: E402,F401  (fixture)


def test_stream_records_history_on_miss_and_on_cache_hit(armed):
    _, calls = armed
    client = TestClient(main.app)
    for _ in range(2):
        resp = client.post("/api/query/stream", json={"query": "levain"})
        assert resp.status_code == 200
    assert calls["stream"] == 1  # the second ask was an answer-cache hit
    entries = client.get("/api/ask/history").json()["entries"]
    assert [e["question"] for e in entries] == ["levain", "levain"]
    assert all(e["answer"] == "Levain likes warmth." for e in entries)
    assert all(len(e["sources"]) == 2 for e in entries)


def test_query_records_history_on_cache_hit(armed):
    _, calls = armed
    client = TestClient(main.app)
    client.post("/api/query", json={"query": "levain"})
    client.post("/api/query", json={"query": "levain"})
    assert calls["chat"] == 1
    assert len(client.get("/api/ask/history").json()["entries"]) == 2


def test_stream_generation_error_is_not_recorded(armed, monkeypatch):
    def broken(messages, max_tokens):
        raise RuntimeError("ollama down")
        yield  # pragma: no cover

    monkeypatch.setattr(main, "ollama_chat_stream", broken)
    client = TestClient(main.app)
    client.post("/api/query/stream", json={"query": "levain"})
    assert client.get("/api/ask/history").json()["entries"] == []


def test_retrieval_cache_does_not_outlive_the_day(armed, monkeypatch):
    coll, _ = armed
    day = [1_800_000_000.0]
    monkeypatch.setattr(main.time, "time", lambda: day[0])
    main.cached_retrieve("levain", scope="notes")
    main.cached_retrieve("levain", scope="notes")
    assert coll.calls == 1
    day[0] += 86400
    main.cached_retrieve("levain", scope="notes")
    assert coll.calls == 2
