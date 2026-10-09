"""POST /api/query/stream and the Ask caches in front of both Ask endpoints.

/api/query is what Ask Anywhere builds on, so these also pin that its
request and response shape did not move when the stream arrived.
"""
import json

import pytest
from fastapi.testclient import TestClient

import main
from tests.test_retrieval import CANNED, FakeCollection, FakeLexical, FakeModel


class CountingCollection(FakeCollection):
    def __init__(self, result):
        super().__init__(result)
        self.calls = 0

    def query(self, **kwargs):
        self.calls += 1
        return super().query(**kwargs)


@pytest.fixture
def armed(monkeypatch):
    """A served engine on fakes, with Ollama replaced in both its modes."""
    coll = CountingCollection(CANNED)
    monkeypatch.setattr(main, "model", FakeModel())
    monkeypatch.setattr(main, "chroma_collection", coll)
    monkeypatch.setattr(main, "lexical_index", None)
    monkeypatch.setattr(main, "cross_encoder", None)
    monkeypatch.setattr(main, "_chroma_stamp_seen", None)  # no real store: no reopen
    monkeypatch.setenv("QUERY_REWRITE", "0")
    calls = {"chat": 0, "stream": 0}

    def fake_chat(messages, max_tokens):
        calls["chat"] += 1
        return "Levain likes warmth."

    def fake_stream(messages, max_tokens):
        calls["stream"] += 1
        yield from ["Levain ", "likes ", "warmth."]

    monkeypatch.setattr(main, "ollama_chat", fake_chat)
    monkeypatch.setattr(main, "ollama_chat_stream", fake_stream)
    return coll, calls


def _events(resp):
    return [json.loads(line) for line in resp.text.splitlines() if line]


def test_query_response_shape_is_unchanged(armed):
    body = TestClient(main.app).post("/api/query", json={"query": "levain"}).json()
    assert set(body) == {"answer", "sources", "api_configured"}
    assert body["answer"] == "Levain likes warmth."
    assert body["api_configured"] is True
    assert [set(s) for s in body["sources"]] == [{"title", "source", "snippet", "distance"}] * 2


def test_stream_sends_sources_first_then_the_answer(armed):
    client = TestClient(main.app)
    resp = client.post("/api/query/stream", json={"query": "levain"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    events = _events(resp)
    assert [e["type"] for e in events] == ["sources", "token", "token", "token", "done"]
    assert "".join(e["text"] for e in events if e["type"] == "token") == "Levain likes warmth."
    # The same sources /api/query returns for the same request.
    main.invalidate_ask_caches()
    assert events[0]["sources"] == client.post("/api/query", json={"query": "levain"}).json()["sources"]
    assert events[0]["api_configured"] is True


def test_stream_keeps_http_errors_before_the_stream_starts(armed, monkeypatch):
    client = TestClient(main.app)
    assert client.post("/api/query/stream", json={"query": "   "}).status_code == 400
    monkeypatch.setattr(main, "model", None)
    assert client.post("/api/query/stream", json={"query": "levain"}).status_code == 503


def test_stream_reports_a_generation_failure_after_the_sources(armed, monkeypatch):
    def broken(messages, max_tokens):
        yield "Lev"
        raise RuntimeError("ollama went away")

    monkeypatch.setattr(main, "ollama_chat_stream", broken)
    events = _events(TestClient(main.app).post("/api/query/stream", json={"query": "levain"}))
    assert [e["type"] for e in events] == ["sources", "token", "error"]
    assert events[-1]["detail"] == "ollama went away"
    assert len(main.answer_cache) == 0  # a partial answer is never cached


def test_repeat_question_is_served_from_cache(armed):
    coll, calls = armed
    client = TestClient(main.app)
    first = client.post("/api/query", json={"query": "levain"}).json()
    second = client.post("/api/query", json={"query": "levain"}).json()
    assert first == second
    assert coll.calls == 1 and calls["chat"] == 1
    # The stream shares both caches: no retrieval, no generation, one token event.
    events = _events(client.post("/api/query/stream", json={"query": "levain"}))
    assert [e["type"] for e in events] == ["sources", "token", "done"]
    assert events[1]["text"] == "Levain likes warmth."
    assert coll.calls == 1 and calls["stream"] == 0


def test_a_streamed_answer_is_cached_for_the_plain_endpoint(armed):
    coll, calls = armed
    client = TestClient(main.app)
    client.post("/api/query/stream", json={"query": "levain"})
    assert client.post("/api/query", json={"query": "levain"}).json()["answer"] == "Levain likes warmth."
    assert calls == {"chat": 0, "stream": 1} and coll.calls == 1


def test_history_and_scope_are_part_of_the_cache_key(armed):
    coll, calls = armed
    client = TestClient(main.app)
    client.post("/api/query", json={"query": "levain"})
    client.post("/api/query", json={"query": "levain", "scope": "all"})
    client.post("/api/query", json={"query": "levain", "history": [{"role": "user", "content": "bread"}]})
    assert coll.calls == 3
    # The answer is keyed by the exact prompt: scope=all retrieved the same
    # chunks here, so it reuses the answer; the history changes the prompt.
    assert calls["chat"] == 2


def test_index_rebuild_invalidates_both_caches(armed, monkeypatch):
    coll, calls = armed
    client = TestClient(main.app)
    client.post("/api/query", json={"query": "levain"})
    # _build_lexical_index runs after every reopen and every ingestion.
    monkeypatch.setattr(main.lexical.LexicalIndex, "build", classmethod(lambda cls, c: FakeLexical([])))
    main._build_lexical_index()
    assert len(main.retrieval_cache) == 0 and len(main.answer_cache) == 0
    client.post("/api/query", json={"query": "levain"})
    assert coll.calls == 2 and calls["chat"] == 2


def test_a_swapped_component_misses_the_retrieval_cache(armed, monkeypatch):
    coll, _ = armed
    client = TestClient(main.app)
    client.get("/api/search", params={"q": "levain"})
    client.get("/api/search", params={"q": "levain"})
    assert coll.calls == 1
    # The reranker finishing its background load must not leave unreranked
    # results in the cache.
    from tests.fakes import OverlapCrossEncoder
    monkeypatch.setattr(main, "cross_encoder", OverlapCrossEncoder())
    client.get("/api/search", params={"q": "levain"})
    assert coll.calls == 2


def test_ttl_zero_disables_the_caches(armed, monkeypatch):
    coll, calls = armed
    monkeypatch.setenv("ASK_CACHE_TTL_SECONDS", "0")
    client = TestClient(main.app)
    client.post("/api/query", json={"query": "levain"})
    client.post("/api/query", json={"query": "levain"})
    assert coll.calls == 2 and calls["chat"] == 2


def test_ollama_chat_stream_yields_pieces_until_done(monkeypatch):
    lines = [
        json.dumps({"message": {"content": "Hel"}, "done": False}),
        "",
        json.dumps({"message": {"content": "lo"}, "done": False}),
        json.dumps({"message": {"content": ""}, "done": True}),
        json.dumps({"message": {"content": "never read"}, "done": False}),
    ]
    seen = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def iter_lines(self):
            return iter(lines)

    class FakeStream:
        def __init__(self, method, url, json, timeout):
            seen.update(method=method, url=url, body=json)

        def __enter__(self):
            return FakeResponse()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(main.httpx, "stream", FakeStream)
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5")
    pieces = list(main.ollama_chat_stream([{"role": "user", "content": "hi"}], max_tokens=7))
    assert pieces == ["Hel", "lo"]
    assert seen["method"] == "POST" and seen["url"].endswith("/api/chat")
    # Same model and options as the non-streamed call; only "stream" differs.
    assert seen["body"] == {**main._ollama_chat_body([{"role": "user", "content": "hi"}], 7, stream=False), "stream": True}
    assert seen["body"]["model"] == "qwen2.5"


def test_ollama_chat_stream_raises_on_an_error_line(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def iter_lines(self):
            return iter([json.dumps({"error": "model not found"})])

    class FakeStream:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return FakeResponse()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(main.httpx, "stream", FakeStream)
    with pytest.raises(RuntimeError, match="model not found"):
        list(main.ollama_chat_stream([], max_tokens=1))
