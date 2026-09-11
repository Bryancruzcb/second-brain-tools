"""Unit tests for optional middling-route LLM classify (TOPIC_LLM_CLASSIFY)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import topic_llm  # noqa: E402


def test_llm_classify_default_off(monkeypatch):
    monkeypatch.delenv("TOPIC_LLM_CLASSIFY", raising=False)
    assert topic_llm.llm_classify_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "YES", "On"])
def test_llm_classify_enabled_values(monkeypatch, value):
    monkeypatch.setenv("TOPIC_LLM_CLASSIFY", value)
    assert topic_llm.llm_classify_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "", "off", "no"])
def test_llm_classify_off_values(monkeypatch, value):
    monkeypatch.setenv("TOPIC_LLM_CLASSIFY", value)
    assert topic_llm.llm_classify_enabled() is False


def test_is_middling_embed_reasons(monkeypatch):
    monkeypatch.setenv("TOPIC_LLM_MIN_EMBED", "0.35")
    # Force re-read of module constant? It is bound at import — patch attribute.
    monkeypatch.setattr(topic_llm, "LLM_MIN_EMBED", 0.35)
    assert topic_llm.is_middling_embed(
        {"reason": "below_threshold", "best": 0.42}
    )
    assert topic_llm.is_middling_embed(
        {"reason": "weak_margin", "best": 0.55}
    )
    assert not topic_llm.is_middling_embed(
        {"reason": "below_threshold", "best": 0.10}
    )
    assert not topic_llm.is_middling_embed(
        {"reason": "unavailable", "best": 0.0}
    )
    assert not topic_llm.is_middling_embed(
        {"reason": "assigned", "best": 0.70}
    )


def test_parse_response_accepts_known_json():
    known = {"second-brain", "chat-inbox", "creatorflow"}
    rid, conf = topic_llm._parse_response(
        '{"id": "second-brain", "confidence": 0.91}', known
    )
    assert rid == "second-brain"
    assert conf == pytest.approx(0.91)


def test_parse_response_rejects_unknown_id():
    known = {"second-brain", "chat-inbox"}
    rid, conf = topic_llm._parse_response(
        '{"id": "not-a-topic", "confidence": 0.99}', known
    )
    assert rid is None
    assert conf == pytest.approx(0.99)


def test_classify_noop_when_disabled(monkeypatch):
    monkeypatch.setenv("TOPIC_LLM_CLASSIFY", "0")
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("should not call ollama")

    monkeypatch.setattr(topic_llm, "_call_ollama", boom)
    route, conf = topic_llm.classify("anything", {"routes": [{"id": "second-brain"}]})
    assert route is None and conf == 0.0
    assert called["n"] == 0


def test_classify_fail_open_on_timeout(monkeypatch):
    monkeypatch.setenv("TOPIC_LLM_CLASSIFY", "1")

    def boom(*a, **k):
        raise TimeoutError("slow")

    monkeypatch.setattr(topic_llm, "_call_ollama", boom)
    cfg = {
        "default_route_id": "chat-inbox",
        "routes": [
            {"id": "second-brain", "title": "Second Brain"},
            {"id": "chat-inbox", "title": "Chat Inbox", "folder": "02 Projects/Chat Inbox"},
        ],
    }
    route, conf = topic_llm.classify("rag chroma vault", cfg)
    assert route is None
    assert conf == 0.0


def test_classify_accepts_high_confidence(monkeypatch):
    monkeypatch.setenv("TOPIC_LLM_CLASSIFY", "1")
    monkeypatch.setattr(topic_llm, "LLM_MIN_CONFIDENCE", 0.75)

    def fake(*a, **k):
        return '{"id": "second-brain", "confidence": 0.88}'

    monkeypatch.setattr(topic_llm, "_call_ollama", fake)
    cfg = {
        "default_route_id": "chat-inbox",
        "routes": [
            {"id": "second-brain", "title": "Second Brain", "folder": "02 Projects/Second Brain"},
            {"id": "chat-inbox", "title": "Chat Inbox", "folder": "02 Projects/Chat Inbox"},
        ],
    }
    route, conf = topic_llm.classify("how does my local rag index work", cfg)
    assert route is not None
    assert route["id"] == "second-brain"
    assert conf == pytest.approx(0.88)


def test_classify_rejects_low_confidence(monkeypatch):
    monkeypatch.setenv("TOPIC_LLM_CLASSIFY", "1")
    monkeypatch.setattr(topic_llm, "LLM_MIN_CONFIDENCE", 0.75)

    def fake(*a, **k):
        return '{"id": "second-brain", "confidence": 0.40}'

    monkeypatch.setattr(topic_llm, "_call_ollama", fake)
    cfg = {
        "default_route_id": "chat-inbox",
        "routes": [
            {"id": "second-brain", "title": "Second Brain"},
            {"id": "chat-inbox", "title": "Chat Inbox"},
        ],
    }
    route, conf = topic_llm.classify("vague chat", cfg)
    assert route is None
    assert conf == pytest.approx(0.40)


def test_route_chat_llm_on_middling_embed(monkeypatch, tmp_path):
    """Keyword miss + middling embed + high-conf LLM → non-inbox stub."""
    import topic_router
    import topic_embed

    monkeypatch.setenv("TOPIC_LLM_CLASSIFY", "1")
    monkeypatch.setattr(topic_llm, "LLM_MIN_CONFIDENCE", 0.75)
    monkeypatch.setattr(topic_llm, "LLM_MIN_EMBED", 0.35)

    cfg = {
        "default_route_id": "chat-inbox",
        "stub_subdir": "AI Chat Links",
        "routes": [
            {
                "id": "second-brain",
                "title": "Second Brain",
                "folder": "02 Projects/Second Brain",
                "keywords": [],
            },
            {
                "id": "chat-inbox",
                "title": "Chat Inbox",
                "folder": "02 Projects/Chat Inbox",
                "keywords": [],
            },
        ],
    }
    monkeypatch.setattr(topic_router, "_load_config", lambda: cfg)
    monkeypatch.setattr(
        topic_embed,
        "embed_decision",
        lambda text, cfg, threshold=None: {
            "route": None,
            "best": 0.45,
            "second": 0.40,
            "margin": 0.04,
            "reason": "below_threshold",
        },
    )
    monkeypatch.setattr(
        topic_llm,
        "_call_ollama",
        lambda *a, **k: '{"id": "second-brain", "confidence": 0.9}',
    )
    # Avoid keyword learning side effects / vault writes complexity:
    monkeypatch.setattr(
        topic_embed,
        "learn_keywords",
        lambda *a, **k: [],
    )
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(topic_router.sb_common, "get_vault_path", lambda: str(vault))

    result = topic_router.route_chat(
        source="Claude",
        title="RAG question",
        date_str="2026-09-10",
        short_id="abcdef123456",
        first_prompt="how does my chroma index rebuild work",
        transcript_link="05 AI Chats/Claude/Coding/sample",
    )
    assert result is not None
    assert result["route"]["id"] == "second-brain"
    assert (vault / "02 Projects" / "Second Brain" / "AI Chat Links").is_dir()


def test_route_chat_skips_llm_when_embed_unavailable(monkeypatch, tmp_path):
    import topic_router
    import topic_embed

    monkeypatch.setenv("TOPIC_LLM_CLASSIFY", "1")
    cfg = {
        "default_route_id": "chat-inbox",
        "stub_subdir": "AI Chat Links",
        "routes": [
            {"id": "second-brain", "title": "Second Brain", "folder": "02 Projects/Second Brain", "keywords": []},
            {"id": "chat-inbox", "title": "Chat Inbox", "folder": "02 Projects/Chat Inbox", "keywords": []},
        ],
    }
    monkeypatch.setattr(topic_router, "_load_config", lambda: cfg)
    monkeypatch.setattr(
        topic_embed,
        "embed_decision",
        lambda *a, **k: {
            "route": None,
            "best": 0.0,
            "second": 0.0,
            "margin": 0.04,
            "reason": "unavailable",
        },
    )
    called = {"n": 0}

    def boom(*a, **k):
        called["n"] += 1
        raise AssertionError("llm should not run")

    monkeypatch.setattr(topic_llm, "_call_ollama", boom)
    monkeypatch.setattr(topic_embed, "learn_keywords", lambda *a, **k: [])
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(topic_router.sb_common, "get_vault_path", lambda: str(vault))

    result = topic_router.route_chat(
        source="Claude",
        title="noise",
        date_str="2026-09-10",
        short_id="abcdef123456",
        first_prompt="hello there",
        transcript_link="05 AI Chats/Claude/Coding/sample",
    )
    assert result is not None
    assert result["route"]["id"] == "chat-inbox"
    assert called["n"] == 0
