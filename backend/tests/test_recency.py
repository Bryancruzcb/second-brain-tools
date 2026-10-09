"""Recency boost and recency-intent widening in shared retrieval."""
import pytest

import lexical
import retrieval
from tests.test_retrieval import FakeLexical, FakeModel

DAY = 86400.0
NOW = 1_800_000_000.0


@pytest.mark.parametrize("text", [
    "what have I been working on lately",
    "What's new in my notes?",
    "summarize my recent notes",
    "anything I wrote this week",
    "what did I do yesterday",
    "notes from the last few days",
    "latest plan for the resume",
])
def test_recency_intent_detected(text):
    assert retrieval.has_recency_intent(text)


@pytest.mark.parametrize("text", [
    "how does the borrow checker work",
    "how do I create a new note",
    "sourdough starter feeding schedule",
    "",
])
def test_no_recency_intent(text):
    assert not retrieval.has_recency_intent(text)


def test_decay_halves_each_half_life_and_ignores_missing_mtime():
    assert retrieval.recency_decay(NOW, now=NOW, half_life_days=30) == pytest.approx(1.0)
    assert retrieval.recency_decay(NOW - 30 * DAY, now=NOW, half_life_days=30) == pytest.approx(0.5)
    assert retrieval.recency_decay(NOW - 60 * DAY, now=NOW, half_life_days=30) == pytest.approx(0.25)
    assert retrieval.recency_decay(NOW + DAY, now=NOW, half_life_days=30) == pytest.approx(1.0)
    assert retrieval.recency_decay(None, now=NOW, half_life_days=30) == 0.0


def _cand(name, score, age_days):
    return {"id": name, "source": f"{name}.md", "title": name, "chunk": name,
            "rerank_score": score, "mtime": None if age_days is None else NOW - age_days * DAY}


def test_mild_boost_breaks_near_ties_toward_newer_note():
    pool = [_cand("old", 5.0, 400), _cand("new", 4.9, 1), _cand("weak", 0.0, 400)]
    out = retrieval.apply_recency(pool, now=NOW)
    assert [c["id"] for c in out] == ["new", "old", "weak"]


def test_mild_boost_keeps_clearly_better_old_note_first():
    pool = [_cand("old", 9.0, 900), _cand("new", 4.0, 0), _cand("weak", 0.0, 900)]
    out = retrieval.apply_recency(pool, now=NOW)
    assert [c["id"] for c in out] == ["old", "new", "weak"]


def test_intent_boost_lifts_recent_note_over_more_relevant_old_one():
    pool = [_cand("old", 9.0, 900), _cand("new", 4.0, 0), _cand("weak", 0.0, 900)]
    out = retrieval.apply_recency(pool, intent=True, now=NOW)
    assert [c["id"] for c in out][0] == "new"


def test_no_mtimes_or_zero_weight_leaves_order_alone(monkeypatch):
    pool = [_cand("a", 1.0, None), _cand("b", 2.0, None)]
    assert retrieval.apply_recency(pool, now=NOW) == pool
    monkeypatch.setenv("ASK_RECENCY_WEIGHT", "0")
    pool = [_cand("a", 5.0, 400), _cand("b", 4.99, 0)]
    assert retrieval.apply_recency(pool, now=NOW) == pool


def test_rank_based_relevance_without_rerank_scores():
    pool = [{"id": str(i), "source": f"{i}.md", "chunk": "", "mtime": NOW - 900 * DAY}
            for i in range(10)]
    pool.append({"id": "fresh", "source": "fresh.md", "chunk": "", "mtime": NOW})
    out = retrieval.apply_recency(pool, now=NOW)
    # Rank 11 of 11 with a full mild boost stays near the bottom...
    assert [c["id"] for c in out].index("fresh") >= 8
    out = retrieval.apply_recency(pool, intent=True, now=NOW)
    # ...but a recency question pulls it well up.
    assert [c["id"] for c in out].index("fresh") <= 5


class _FakeChromaGet:
    def __init__(self, rows):
        self.rows = rows

    def get(self, include=None):
        return {
            "ids": [r[0] for r in self.rows],
            "documents": [r[1] for r in self.rows],
            "metadatas": [r[2] for r in self.rows],
        }


def test_lexical_carries_mtime_and_lists_recent_notes_once_each():
    rows = [
        ("o1", "old garden compost", {"source": "old.md", "title": "Old", "mtime": NOW - 90 * DAY}),
        ("n1", "new project kickoff", {"source": "new.md", "title": "New", "mtime": NOW}),
        ("n2", "new project second chunk", {"source": "new.md", "title": "New", "mtime": NOW}),
        ("c1", "chat transcript", {"source": "chat.md", "title": "Chat", "category": "chat", "mtime": NOW}),
        ("x1", "no mtime here", {"source": "x.md", "title": "X"}),
    ]
    idx = lexical.LexicalIndex.build(_FakeChromaGet(rows))
    hits = idx.search("garden compost", scope="notes", k=5)
    assert hits[0]["mtime"] == NOW - 90 * DAY
    recent = idx.recent(scope="notes", k=5)
    assert [r["source"] for r in recent] == ["new.md", "old.md"]
    assert recent[0]["id"] == "n1"
    assert [r["source"] for r in idx.recent(scope="chats", k=5)] == ["chat.md"]
    assert idx.recent(k=0) == []


class _RecentLexical(FakeLexical):
    def __init__(self, results, recent):
        super().__init__(results)
        self._recent = recent

    def recent(self, scope="notes", k=10):
        return self._recent[:k]


class _Coll:
    def __init__(self, rows):
        self.rows = rows

    def query(self, **kwargs):
        return {
            "ids": [[r["id"] for r in self.rows]],
            "documents": [[r["chunk"] for r in self.rows]],
            "metadatas": [[{"source": r["source"], "title": r["title"], "mtime": r["mtime"]}
                           for r in self.rows]],
            "distances": [[0.1 * (i + 1) for i in range(len(self.rows))]],
        }


def _setup(monkeypatch):
    monkeypatch.setenv("NOTES_CHAT_GUARD", "0")
    monkeypatch.setenv("QUERY_REWRITE", "0")
    monkeypatch.setenv("MAX_CHUNKS_PER_NOTE", "0")
    old = [{"id": f"old{i}", "source": f"old{i}.md", "title": f"Old {i}",
            "chunk": f"working project notes {i}", "mtime": 1.0} for i in range(3)]
    fresh = {"id": "fresh", "source": "fresh.md", "title": "Fresh",
             "chunk": "today I shipped the atlas fix", "mtime": __import__("time").time()}
    return _Coll(old), _RecentLexical(old, [fresh])


def test_recency_question_pulls_in_recent_notes_the_search_missed(monkeypatch):
    coll, lex = _setup(monkeypatch)
    out = retrieval.retrieve_hybrid("what have I been working on lately", model=FakeModel(),
                                    collection=coll, lexical=lex, k=4)
    ids = [c["id"] for c in out]
    # Without a reranker the injected note starts last; the intent boost
    # still lifts it above weaker old matches.
    assert "fresh" in ids
    assert ids.index("fresh") < ids.index("old2")


def test_recency_question_with_reranker_puts_comparable_recent_note_first(monkeypatch):
    from tests.fakes import OverlapCrossEncoder
    coll, lex = _setup(monkeypatch)
    out = retrieval.retrieve_hybrid("what have I been working on lately", model=FakeModel(),
                                    collection=coll, lexical=lex,
                                    cross_encoder=OverlapCrossEncoder(), k=4)
    assert out[0]["id"] == "fresh"


def test_ordinary_question_does_not_widen_the_pool(monkeypatch):
    coll, lex = _setup(monkeypatch)
    out = retrieval.retrieve_hybrid("working project notes", model=FakeModel(),
                                    collection=coll, lexical=lex, k=4)
    assert "fresh" not in [c["id"] for c in out]
