"""Unit tests for NOTES_CHAT_GUARD and SIBLING_DISAMBIG (default OFF)."""
import retrieval


def _cand(cid, source, title=None, chunk=None, rrf=None):
    out = {
        "id": cid,
        "source": source,
        "title": title or cid,
        "chunk": chunk or f"chunk {cid}",
        "distance": 0.1,
    }
    if rrf is not None:
        out["rrf_score"] = rrf
    return out


def test_notes_chat_guard_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NOTES_CHAT_GUARD", raising=False)
    import config
    assert config.notes_chat_guard_enabled() is False
    cands = [
        _cand("n", "03 School/School Notes.md", "School Notes"),
        _cand("c", "03 School/AI Chat Links/2026-05-16 - foo - abc.md", "foo"),
    ]
    assert retrieval.filter_notes_chat_guard(cands, "notes") == cands


def test_notes_chat_guard_filters_chat_stubs_on_notes_scope(monkeypatch):
    monkeypatch.setenv("NOTES_CHAT_GUARD", "1")
    note = _cand("n", "03 School/School Notes.md", "School Notes")
    stub = _cand("s", "02 Projects/AI Chat Links/2026-08-07 - consolidate - 019fdd.md", "consolidate")
    chat = _cand("c", "05 AI Chats/Claude/Coding/2026-07-23 - Pipeline - 8bcdc9.md", "Pipeline")
    out = retrieval.filter_notes_chat_guard([stub, note, chat], "notes")
    assert [c["id"] for c in out] == ["n"]


def test_notes_chat_guard_skips_chats_scope(monkeypatch):
    monkeypatch.setenv("NOTES_CHAT_GUARD", "1")
    chat = _cand("c", "05 AI Chats/Claude/Personal/2026-07-19 - Resume Rebuild - 757.md", "Resume")
    out = retrieval.filter_notes_chat_guard([chat], "chats")
    assert out == [chat]


def test_notes_chat_guard_fail_open_if_all_filtered(monkeypatch):
    monkeypatch.setenv("NOTES_CHAT_GUARD", "1")
    stub = _cand("s", "03 School/AI Chat Links/x.md", "x")
    out = retrieval.filter_notes_chat_guard([stub], "notes")
    assert out == [stub]


def test_sibling_disambig_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SIBLING_DISAMBIG", raising=False)
    import config
    assert config.sibling_disambig_enabled() is False
    missed = _cand("m", "03 School/CS146/Questions I Missed.md", "Questions I Missed", rrf=0.03)
    home = _cand("h", "03 School/CS146/Course Home.md", "Course Home", rrf=0.02)
    out = retrieval.sibling_disambiguate(
        "wrong container for the job", [missed, home]
    )
    assert [c["id"] for c in out] == ["m", "h"]


def test_sibling_disambig_prefers_course_home_over_sibling(monkeypatch):
    monkeypatch.setenv("SIBLING_DISAMBIG", "1")
    missed = _cand("m", "03 School/CS146/Questions I Missed.md", "Questions I Missed", rrf=0.03)
    home = _cand("h", "03 School/CS146/Course Home.md", "Course Home", rrf=0.02)
    out = retrieval.sibling_disambiguate(
        "errors when they reach for the wrong container for the job",
        [missed, home],
    )
    assert out[0]["id"] == "h"


def test_sibling_disambig_boosts_resume_title(monkeypatch):
    monkeypatch.setenv("SIBLING_DISAMBIG", "1")
    noise = _cand(
        "n",
        "05 AI Chats/Claude/Coding/2026-09-04 - improvements - a2.md",
        "improvements",
        rrf=0.03,
    )
    resume = _cand(
        "r",
        "05 AI Chats/Claude/Personal/2026-07-19 - Resume Rebuild and Job Hunt Setup - 757.md",
        "Resume Rebuild and Job Hunt Setup",
        rrf=0.02,
    )
    out = retrieval.sibling_disambiguate(
        "in the session where i redid my resume, what did we end up with?",
        [noise, resume],
    )
    assert out[0]["id"] == "r"


def test_hybrid_applies_notes_chat_guard_before_rerank(monkeypatch):
    monkeypatch.setenv("NOTES_CHAT_GUARD", "1")
    monkeypatch.delenv("SIBLING_DISAMBIG", raising=False)
    monkeypatch.delenv("QUERY_REWRITE", raising=False)
    from tests.test_retrieval import FakeCollection, FakeModel, FakeLexical
    from tests.fakes import OverlapCrossEncoder

    canned = {
        "ids": [["stub", "note"]],
        "documents": [["chat stub tokens xyz", "school slides exam studying"]],
        "metadatas": [[
            {"source": "03 School/AI Chat Links/stub.md", "title": "stub"},
            {"source": "03 School/School Notes.md", "title": "School Notes"},
        ]],
        "distances": [[0.1, 0.2]],
    }
    out = retrieval.retrieve_hybrid(
        "school slides exam studying",
        model=FakeModel(),
        collection=FakeCollection(canned),
        lexical=FakeLexical([]),
        cross_encoder=OverlapCrossEncoder(),
        scope="notes",
        k=2,
    )
    assert out[0]["id"] == "note"
    assert all("AI Chat Links" not in c["source"] for c in out)


def test_sibling_disambig_post_ce_prefers_course_home(monkeypatch):
    monkeypatch.setenv("SIBLING_DISAMBIG", "1")
    missed = _cand("m", "03 School/CS146/Questions I Missed.md", "Questions I Missed")
    home = _cand("h", "03 School/CS146/Course Home.md", "Course Home")
    missed["rerank_score"] = 1.0
    home["rerank_score"] = 0.5
    out = retrieval.sibling_disambiguate(
        "errors when they reach for the wrong container for the job",
        [missed, home],
        score_key="rerank_score",
    )
    assert out[0]["id"] == "h"

