"""Unit tests for retrieval query rewrite (QUERY_REWRITE flag)."""
import httpx
import pytest

import config
import query_rewrite
import retrieval
from tests.test_retrieval import CANNED, FakeCollection, FakeModel


def test_query_rewrite_enabled_by_default(monkeypatch):
    monkeypatch.delenv("QUERY_REWRITE", raising=False)
    assert config.query_rewrite_enabled() is True
    assert query_rewrite.query_rewrite_enabled() is True


@pytest.mark.parametrize("value", ["1", "true", "YES", "On"])
def test_query_rewrite_enabled_values(monkeypatch, value):
    monkeypatch.setenv("QUERY_REWRITE", value)
    assert config.query_rewrite_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "", "off", "no"])
def test_query_rewrite_off_values(monkeypatch, value):
    monkeypatch.setenv("QUERY_REWRITE", value)
    assert config.query_rewrite_enabled() is False


def test_merge_rewrite_appends_new_tokens_keeps_original():
    out = query_rewrite.merge_rewrite(
        "city portal into the app",
        "city open data portal application UI",
    )
    assert out.startswith("city portal into the app")
    assert "application" in out
    assert "UI" in out
    # Overlapping tokens stay in the appended phrase (not stripped).
    assert "portal" in out[len("city portal into the app"):]


def test_merge_rewrite_caps_tokens_and_clauses():
    long = ", ".join([f"syn{i}" for i in range(12)])
    out = query_rewrite.merge_rewrite("base query", long)
    extras = out[len("base query"):].split()
    assert len(extras) <= query_rewrite.REWRITE_MAX_TOKENS
    # At most two comma/semicolon clauses contribute.
    assert out.startswith("base query")


def test_merge_rewrite_empty_or_duplicate_returns_original():
    assert query_rewrite.merge_rewrite("hello world", "") == "hello world"
    assert query_rewrite.merge_rewrite("hello world", "hello world") == "hello world"
    assert query_rewrite.merge_rewrite("hello world", "Rewritten: hello world") == "hello world"
    # Case-insensitive duplicate still returns original only.
    assert query_rewrite.merge_rewrite("Hello World", "hello world") == "Hello World"


def test_rewrite_for_retrieval_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("QUERY_REWRITE", "0")
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("should not call ollama")

    monkeypatch.setattr(query_rewrite, "_call_ollama_rewrite", boom)
    assert query_rewrite.rewrite_for_retrieval("my question") == "my question"
    assert called["n"] == 0


def test_rewrite_for_retrieval_fail_open_on_timeout(monkeypatch):
    monkeypatch.setenv("QUERY_REWRITE", "1")

    def boom(q):
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr(query_rewrite, "_call_ollama_rewrite", boom)
    assert query_rewrite.rewrite_for_retrieval("original q") == "original q"


def test_rewrite_for_retrieval_merges_model_output(monkeypatch):
    monkeypatch.setenv("QUERY_REWRITE", "1")
    monkeypatch.setattr(
        query_rewrite,
        "_call_ollama_rewrite",
        lambda q: "virtualenv requirements.txt setup",
    )
    out = query_rewrite.rewrite_for_retrieval("set up the virtual environment")
    assert "set up the virtual environment" in out
    assert "virtualenv" in out or "requirements.txt" in out


def test_retrieve_hybrid_uses_rewritten_query_when_enabled(monkeypatch):
    monkeypatch.setenv("QUERY_REWRITE", "1")
    monkeypatch.setattr(
        query_rewrite,
        "_call_ollama_rewrite",
        lambda q: "architecture application UI portal",
    )
    coll = FakeCollection(CANNED)
    seen = {}

    real_retrieve = retrieval.retrieve

    def spy(query_text, **kwargs):
        seen["q"] = query_text
        return real_retrieve(query_text, **kwargs)

    monkeypatch.setattr(retrieval, "retrieve", spy)
    retrieval.retrieve_hybrid("city portal into the app", model=FakeModel(), collection=coll)
    assert "city portal into the app" in seen["q"]
    assert "architecture" in seen["q"] or "application" in seen["q"] or "UI" in seen["q"]


def test_retrieve_hybrid_unchanged_when_rewrite_off(monkeypatch):
    monkeypatch.setenv("QUERY_REWRITE", "0")
    coll = FakeCollection(CANNED)
    seen = {}
    real_retrieve = retrieval.retrieve

    def spy(query_text, **kwargs):
        seen["q"] = query_text
        return real_retrieve(query_text, **kwargs)

    monkeypatch.setattr(retrieval, "retrieve", spy)
    retrieval.retrieve_hybrid("exact query text", model=FakeModel(), collection=coll)
    assert seen["q"] == "exact query text"


def test_domain_hint_expansions_cover_prompt_cases():
    assert "architecture" in query_rewrite.domain_hint_expansions(
        "city's open portal into the app"
    )
    assert "inspect" in query_rewrite.domain_hint_expansions(
        "reading through existing code before i change anything"
    )
    assert "virtualenv" in query_rewrite.domain_hint_expansions(
        "set up the virtual environment and pull in the requirements"
    )
    assert query_rewrite.domain_hint_expansions("clean keyword query") == ""


def test_rewrite_includes_domain_hints_even_if_model_skips_them(monkeypatch):
    monkeypatch.setenv("QUERY_REWRITE", "1")
    monkeypatch.setattr(query_rewrite, "_call_ollama_rewrite", lambda q: "data flow")
    query_rewrite._rewrite_cached.cache_clear()
    out = query_rewrite.rewrite_for_retrieval(
        "how does the data get from the city's open portal all the way into the app?"
    )
    assert "architecture" in out
    assert "application" in out or "UI" in out

def test_introduces_forbidden_chat_terms_detects_new_leaks():
    assert query_rewrite.introduces_forbidden_chat_terms(
        "cleanup script handwritten notes",
        "chat transcript about cleanup",
    )
    assert not query_rewrite.introduces_forbidden_chat_terms(
        "resume chat session",
        "resume rebuild chat",
    )
    assert not query_rewrite.introduces_forbidden_chat_terms(
        "cleanup script",
        "handwritten notes recovery",
    )


def test_rewrite_rejects_model_output_that_adds_chat_terms(monkeypatch):
    monkeypatch.setenv("QUERY_REWRITE", "1")
    monkeypatch.setattr(
        query_rewrite,
        "_call_ollama_rewrite",
        lambda q: "slack thread transcript about notes",
    )
    query_rewrite._rewrite_cached.cache_clear()
    out = query_rewrite.rewrite_for_retrieval("cleanup script deleted handwritten notes")
    assert "cleanup script deleted handwritten notes" in out
    assert "slack" not in out.casefold()
    assert "thread" not in out.casefold()
    assert "transcript" not in out.casefold()
    # Deterministic hints still apply.
    assert "hand-written" in out.casefold() or "clean_empty_chats" in out


def test_domain_hint_expansions_cover_remaining_miss_cues():
    slides = query_rewrite.domain_hint_expansions(
        "how did i plan to break up the slides i have left before a test?"
    )
    assert "slides" in slides and "exam" in slides
    container = query_rewrite.domain_hint_expansions(
        "wrong container for the job"
    )
    assert "Course Home" in container or "data structure" in container
    cleanup = query_rewrite.domain_hint_expansions(
        "the cleanup script deleted my handwritten session notes"
    )
    assert "clean_empty_chats" in cleanup and "hand-written" in cleanup
    resume = query_rewrite.domain_hint_expansions(
        "in the session where i redid my resume"
    )
    assert "Resume" in resume or "rebuild" in resume.casefold()


# ── the Ollama call itself ────────────────────────────────────────────────

def _fake_stream(monkeypatch, lines):
    """httpx.stream double: records the request and how many lines were read."""
    seen = {"read": 0}

    class Response:
        def raise_for_status(self):
            pass

        def iter_lines(self):
            for line in lines:
                seen["read"] += 1
                yield line

    class Stream:
        def __init__(self, method, url, json, timeout):
            seen.update(method=method, url=url, body=json)

        def __enter__(self):
            return Response()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(query_rewrite.httpx, "stream", Stream)
    return seen


def _piece(text, done=False):
    import json
    return json.dumps({"message": {"content": text}, "done": done})


def test_rewrite_asks_for_the_answer_calls_context_window(monkeypatch):
    # A different num_ctx makes Ollama unload the model and load it again,
    # once for the rewrite and once more for the answer that follows.
    import main
    monkeypatch.setenv("OLLAMA_NUM_CTX", "12288")
    seen = _fake_stream(monkeypatch, [_piece("levain starter", done=True)])
    assert query_rewrite._call_ollama_rewrite("levain") == "levain starter"
    answer_body = main._ollama_chat_body([], main.ASK_MAX_TOKENS, stream=True)
    assert seen["body"]["options"]["num_ctx"] == answer_body["options"]["num_ctx"] == 12288
    assert seen["body"]["model"] == answer_body["model"]
    assert seen["body"]["stream"] is True and seen["method"] == "POST"


def test_rewrite_stops_reading_after_the_first_complete_line(monkeypatch):
    seen = _fake_stream(monkeypatch, [
        _piece("\n"),               # leading blank line: keep reading
        _piece("sourdough "),
        _piece("levain\nExplanation"),
        _piece(": never read"),
        _piece("", done=True),
    ])
    text = query_rewrite._call_ollama_rewrite("bread")
    assert seen["read"] == 3
    assert query_rewrite._clean_model_output(text) == "sourdough levain"


def test_rewrite_raises_on_an_ollama_error_line_and_fails_open(monkeypatch):
    import json
    _fake_stream(monkeypatch, [json.dumps({"error": "model not found"})])
    with pytest.raises(RuntimeError, match="model not found"):
        query_rewrite._call_ollama_rewrite("bread")
    monkeypatch.setenv("QUERY_REWRITE", "1")
    query_rewrite._rewrite_cached.cache_clear()
    assert query_rewrite.rewrite_for_retrieval("bread") == "bread"
    query_rewrite._rewrite_cached.cache_clear()
