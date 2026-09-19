"""The scrape endpoint answers, and it never names a note.

Every alert email, dashboard panel and scrape response is less private than
the vault itself, so the label rules in metrics.py get tests rather than a
comment.
"""
import pytest
from fastapi.testclient import TestClient

import main
import metrics
import retrieval
from tests.test_retrieval import FakeModel, FakeCollection, CANNED


def scrape(client=None):
    resp = (client or TestClient(main.app)).get("/metrics")
    assert resp.status_code == 200
    return resp.text


def sample(body, name):
    """The value of a single unlabelled sample in the scrape body."""
    for line in body.splitlines():
        if line.startswith(name + " "):
            return float(line.split()[1])
    raise AssertionError(f"{name} missing from the scrape:\n{body[:2000]}")


def test_scrape_exposes_the_four_app_metrics_and_the_http_ones():
    body = scrape()
    for name in (
        "second_brain_retrieval_seconds",
        "second_brain_rerank_seconds",
        "second_brain_collection_chunks",
        "second_brain_index_age_seconds",
        "http_request_duration_seconds",
        "http_requests_total",
    ):
        assert name in body


def test_latency_buckets_include_the_alert_threshold():
    """Week 3 alerts on p95 above 1.5 s; interpolating to it would be a guess."""
    body = scrape()
    assert 'le="1.5"' in body


def test_a_note_title_never_reaches_a_label():
    client = TestClient(main.app)
    client.get("/api/note/Therapy Notes 2026.md")        # templated route, 404s
    client.get("/no-such-route/Therapy Notes 2026.md")   # untemplated, 404s
    body = scrape(client)
    assert "Therapy" not in body
    assert 'handler="/api/note/{note_ref:path}"' in body


def test_search_records_retrieval_latency(monkeypatch):
    monkeypatch.setattr(main, "model", FakeModel())
    monkeypatch.setattr(main, "chroma_collection", FakeCollection(CANNED))
    monkeypatch.setattr(main, "lexical_index", None)
    client = TestClient(main.app)
    before = sample(scrape(client), "second_brain_retrieval_seconds_count")
    assert client.get("/api/search", params={"q": "alpha"}).status_code == 200
    assert sample(scrape(client), "second_brain_retrieval_seconds_count") == before + 1


def test_rerank_records_its_own_latency():
    class FakeCrossEncoder:
        def predict(self, pairs, **_):
            return [0.5] * len(pairs)

    before = sample(scrape(), "second_brain_rerank_seconds_count")
    retrieval.rerank("q", [{"chunk": "c", "source": "a.md"}], cross_encoder=FakeCrossEncoder(), k=1)
    assert sample(scrape(), "second_brain_rerank_seconds_count") == before + 1


def test_index_age_resets_when_the_stamp_moves(monkeypatch):
    stamps = iter([(("seg", 1),), (("seg", 1),), (("seg", 2),)])
    monkeypatch.setattr(main, "_chroma_write_stamp", lambda *a, **k: next(stamps))
    monkeypatch.setattr(main, "_index_stamp_metric", None)
    monkeypatch.setattr(main, "_index_changed_at", 0.0)  # an ancient index

    assert main._index_age_seconds() > 1_000_000   # seeding does not claim a write
    assert main._index_age_seconds() > 1_000_000   # unchanged stamp, still ancient
    assert main._index_age_seconds() < 5           # the stamp moved: fresh


def test_index_age_leaves_the_reopen_stamp_alone(monkeypatch):
    """The gauge must not eat the signal ensure_chroma_fresh reopens on.

    Advancing _chroma_stamp_seen from the metrics path would mark an
    external write as already seen, and the stale Chroma view fixed in
    PR #25 would be back with no test failing.
    """
    monkeypatch.setattr(main, "_chroma_write_stamp", lambda *a, **k: (("seg", 9),))
    monkeypatch.setattr(main, "_chroma_stamp_seen", (("seg", 1),))
    monkeypatch.setattr(main, "_index_stamp_metric", None)
    main._index_age_seconds()
    assert main._chroma_stamp_seen == (("seg", 1),)


def test_collection_count_reads_the_live_collection(monkeypatch):
    class Counting:
        def count(self):
            return 4321

    monkeypatch.setattr(main, "chroma_collection", Counting())
    assert main._collection_chunk_count() == 4321.0


def test_collection_count_holds_its_last_value_through_an_error(monkeypatch):
    class Broken:
        def count(self):
            raise RuntimeError("store is mid-swap")

    monkeypatch.setattr(main, "_collection_chunks_last", 99.0)
    monkeypatch.setattr(main, "chroma_collection", Broken())
    assert main._collection_chunk_count() == 99.0   # a stale gauge beats a 500 scrape
