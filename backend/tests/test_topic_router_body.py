"""Routing should read the saved transcript, not just the first prompt."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import topic_router  # noqa: E402


CFG = {
    "default_route_id": "chat-inbox",
    "stub_subdir": "AI Chat Links",
    "routes": [
        {
            "id": "second-brain",
            "title": "Second Brain",
            "folder": "02 Projects/Second Brain",
            "keywords": ["chroma", "local rag"],
        },
        {
            "id": "chat-inbox",
            "title": "Chat Inbox",
            "folder": "02 Projects/Chat Inbox",
            "keywords": [],
        },
    ],
}


def _patch(monkeypatch, tmp_path):
    monkeypatch.setattr(topic_router, "_load_config", lambda: CFG)
    monkeypatch.setattr(topic_router, "topic_embed", None)
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(topic_router.sb_common, "get_vault_path", lambda: str(vault))
    return vault


def test_generic_opener_without_body_goes_to_inbox(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    result = topic_router.route_chat(
        source="Claude",
        title="hey can you help",
        date_str="2026-09-10",
        short_id="abcdef123456",
        first_prompt="hey can you help",
        transcript_link="05 AI Chats/Claude/Coding/sample",
    )
    assert result is not None
    assert result["route"]["id"] == "chat-inbox"


def test_transcript_body_keyword_beats_generic_opener(monkeypatch, tmp_path):
    _patch(monkeypatch, tmp_path)
    transcript = tmp_path / "chat.md"
    transcript.write_text(
        "hey can you help\n\nplease rebuild the chroma local rag index\n",
        encoding="utf-8",
    )
    result = topic_router.route_chat(
        source="Claude",
        title="hey can you help",
        date_str="2026-09-10",
        short_id="abcdef123456",
        first_prompt="hey can you help",
        transcript_path=str(transcript),
        transcript_link="05 AI Chats/Claude/Coding/sample",
    )
    assert result is not None
    assert result["route"]["id"] == "second-brain"
