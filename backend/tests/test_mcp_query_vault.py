"""query_vault in mcp_server.py, against a mocked backend.

The MCP SDK lives in requirements-mcp.txt, not requirements-dev.txt, so this
module skips where it is not installed (the CI test job). Install it locally
to run these: pip install -r backend/requirements-mcp.txt
"""
import httpx
import pytest

pytest.importorskip("mcp")

import mcp_server  # noqa: E402

READY = {"ready": True, "index_populated": True, "components": {"embedding_model": True}}


class FakeBackend:
    """Stands in for httpx.get/httpx.post and records what was sent."""

    def __init__(self, query_status=200, query_body=None, ready_body=READY, query_exc=None):
        self.query_status = query_status
        self.query_body = query_body if query_body is not None else {
            "answer": "According to your notes on Levain, feed it at 1:1:1.",
            "sources": [
                {"title": "Levain", "source": "Baking/Levain.md", "snippet": "...", "distance": 0.12},
            ],
            "api_configured": True,
        }
        self.ready_body = ready_body
        self.query_exc = query_exc
        self.posts = []

    def get(self, url, **kwargs):
        assert url.endswith("/api/ready")
        return httpx.Response(200, json=self.ready_body, request=httpx.Request("GET", url))

    def post(self, url, json=None, timeout=None, **kwargs):
        self.posts.append({"url": url, "json": json, "timeout": timeout})
        if self.query_exc:
            raise self.query_exc
        return httpx.Response(
            self.query_status, json=self.query_body, request=httpx.Request("POST", url)
        )


@pytest.fixture
def backend(monkeypatch):
    fake = FakeBackend()
    monkeypatch.setattr(mcp_server.httpx, "get", fake.get)
    monkeypatch.setattr(mcp_server.httpx, "post", fake.post)
    return fake


def test_posts_the_existing_query_contract(backend):
    out = mcp_server.query_vault("  how do I feed my levain?  ", scope="all")

    assert len(backend.posts) == 1
    sent = backend.posts[0]
    assert sent["url"] == f"{mcp_server.BACKEND_URL}/api/query"
    # Exactly the QueryRequest fields main.py accepts; no context_nodes unless asked.
    assert sent["json"] == {"query": "how do I feed my levain?", "scope": "all"}
    assert sent["timeout"] == mcp_server.QUERY_TIMEOUT_SECONDS
    assert out.startswith("According to your notes on Levain")
    assert "Sources:\n1. Levain (Baking/Levain.md)" in out


def test_notes_become_context_nodes(backend):
    mcp_server.query_vault("summarize", notes=["Baking/Levain.md", "Compost Bin.md"])
    assert backend.posts[0]["json"]["context_nodes"] == ["Baking/Levain.md", "Compost Bin.md"]


def test_blank_question_never_calls_backend(backend):
    assert mcp_server.query_vault("   ") == "No question given."
    assert backend.posts == []


def test_cold_backend_is_reported_not_queried(backend):
    backend.ready_body = {"ready": False, "components": {"lexical_index": False, "reranker": True}}
    out = mcp_server.query_vault("anything")
    assert "still loading: lexical_index" in out
    assert backend.posts == []


def test_backend_error_detail_is_passed_through(backend):
    backend.query_status = 500
    backend.query_body = {"detail": "model 'qwen3' not found"}
    out = mcp_server.query_vault("anything")
    assert out == "The backend could not answer: HTTP 500: model 'qwen3' not found."


def test_timeout_names_the_knob(backend):
    backend.query_exc = httpx.ReadTimeout("slow")
    out = mcp_server.query_vault("anything")
    assert "SECOND_BRAIN_MCP_QUERY_TIMEOUT" in out


def test_unreachable_backend(backend):
    backend.query_exc = httpx.ConnectError("refused")
    out = mcp_server.query_vault("anything")
    assert out.startswith("Could not reach the Second Brain backend")


def test_answer_without_sources(backend):
    backend.query_body = {"answer": "Nothing in your notes covers that.", "sources": [], "api_configured": True}
    assert mcp_server.query_vault("anything") == "Nothing in your notes covers that."
