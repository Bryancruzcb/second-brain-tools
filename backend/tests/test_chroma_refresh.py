"""The backend's Chroma view goes stale when another process writes the store
(the nightly indexer, scripts/rebuild_rag_index.py). These pin the detection,
reopen and retry path in main.py. The production symptom was Ask answering
500 "Error finding id" on every scoped query until someone restarted uvicorn.
"""
import subprocess
import sys
import textwrap
import time

import chromadb
from fastapi.testclient import TestClient

import main
from tests.test_retrieval import CANNED, FakeCollection, FakeModel

STALE = "Error executing plan: Internal error: Error finding id"


class StaleOnceCollection(FakeCollection):
    """Raises Chroma's stale-index error on the first query, then behaves."""

    def __init__(self, result):
        super().__init__(result)
        self.calls = 0

    def query(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError(STALE)
        return super().query(**kwargs)


def _arm(monkeypatch, coll):
    monkeypatch.setattr(main, "model", FakeModel())
    monkeypatch.setattr(main, "chroma_collection", coll)
    monkeypatch.setattr(main, "lexical_index", None)
    monkeypatch.setattr(main, "cross_encoder", None)
    monkeypatch.setattr(main, "_chroma_stamp_seen", None)  # no real store: no proactive reopen
    monkeypatch.setattr(main, "_chroma_generation", 0)
    monkeypatch.setattr(main, "ollama_chat", lambda messages, max_tokens: "answer")


def _record_reopens(monkeypatch):
    reasons = []

    def fake_reopen(reason, expected_stamp=None):
        reasons.append(reason)
        main._chroma_generation += 1
        return True

    monkeypatch.setattr(main, "reopen_chroma", fake_reopen)
    return reasons


# ── the retry path ────────────────────────────────────────────────────────

def test_query_heals_a_stale_store_once(monkeypatch):
    coll = StaleOnceCollection(CANNED)
    _arm(monkeypatch, coll)
    reopens = _record_reopens(monkeypatch)
    resp = TestClient(main.app).post("/api/query", json={"query": "x", "scope": "notes"})
    assert resp.status_code == 200
    assert [s["title"] for s in resp.json()["sources"]] == ["A", "B"]
    assert coll.calls == 2
    assert len(reopens) == 1 and "query failed" in reopens[0]


def test_search_heals_a_stale_store_once(monkeypatch):
    coll = StaleOnceCollection(CANNED)
    _arm(monkeypatch, coll)
    reopens = _record_reopens(monkeypatch)
    resp = TestClient(main.app).get("/api/search", params={"q": "x", "scope": "notes"})
    assert resp.status_code == 200
    # Before the fix this endpoint swallowed the error and answered [] —
    # which is what the smoke test on BryansDell saw.
    assert [r["title"] for r in resp.json()["results"]] == ["A", "B"]
    assert coll.calls == 2 and len(reopens) == 1


def test_a_store_still_stale_after_reopen_is_a_500_not_a_loop(monkeypatch):
    class AlwaysStale(FakeCollection):
        def query(self, **kwargs):
            raise RuntimeError(STALE)

    _arm(monkeypatch, AlwaysStale(CANNED))
    reopens = _record_reopens(monkeypatch)
    resp = TestClient(main.app).post("/api/query", json={"query": "x"})
    assert resp.status_code == 500
    assert "Error finding id" in resp.json()["detail"]
    assert len(reopens) == 1


def test_other_errors_are_not_retried(monkeypatch):
    class Broken(FakeCollection):
        def query(self, **kwargs):
            raise RuntimeError("boom")

    _arm(monkeypatch, Broken(CANNED))
    reopens = _record_reopens(monkeypatch)
    assert TestClient(main.app).post("/api/query", json={"query": "x"}).status_code == 500
    assert reopens == []


def test_retry_skips_the_reopen_when_another_request_already_did(monkeypatch):
    class StaleUntilConcurrentReopen(StaleOnceCollection):
        def query(self, **kwargs):
            if self.calls == 0:
                main._chroma_generation += 1  # a parallel request reopened meanwhile
            return super().query(**kwargs)

    coll = StaleUntilConcurrentReopen(CANNED)
    _arm(monkeypatch, coll)
    reopens = _record_reopens(monkeypatch)
    resp = TestClient(main.app).post("/api/query", json={"query": "x"})
    assert resp.status_code == 200
    assert coll.calls == 2 and reopens == []


# ── the proactive check ───────────────────────────────────────────────────

def _track(monkeypatch, seen=("old",), now=("new",), ingesting=False, last_reopen=float("-inf")):
    monkeypatch.setattr(main, "_chroma_stamp_seen", seen)
    monkeypatch.setattr(main, "chroma_client", object())
    monkeypatch.setattr(main, "_ingesting", ingesting)
    monkeypatch.setattr(main, "_chroma_last_reopen", last_reopen)
    monkeypatch.setattr(main, "_chroma_write_stamp", lambda db_path=None: now)
    monkeypatch.setattr(main, "_chroma_generation", 0)
    return _record_reopens(monkeypatch)


def test_ensure_fresh_reopens_when_the_stamp_moved(monkeypatch):
    reopens = _track(monkeypatch)
    assert main.ensure_chroma_fresh() is True
    assert len(reopens) == 1 and "write stamp moved" in reopens[0]


def test_ensure_fresh_is_quiet_when_nothing_was_written(monkeypatch):
    reopens = _track(monkeypatch, seen=("same",), now=("same",))
    assert main.ensure_chroma_fresh() is False and reopens == []


def test_ensure_fresh_is_a_noop_without_a_tracked_store(monkeypatch):
    reopens = _track(monkeypatch, seen=None)
    assert main.ensure_chroma_fresh() is False and reopens == []


def test_ensure_fresh_waits_while_this_process_is_ingesting(monkeypatch):
    reopens = _track(monkeypatch, ingesting=True)
    assert main.ensure_chroma_fresh() is False and reopens == []


def test_ensure_fresh_respects_the_cooldown(monkeypatch):
    reopens = _track(monkeypatch, last_reopen=time.monotonic())
    assert main.ensure_chroma_fresh() is False and reopens == []


def test_refresh_endpoint_reopens_a_real_store(monkeypatch):
    monkeypatch.setattr(main, "chroma_collection", object())
    monkeypatch.setattr(main, "chroma_client", object())
    monkeypatch.setattr(main, "lexical_index", None)
    monkeypatch.setattr(main, "_chroma_generation", 0)
    reopens = _record_reopens(monkeypatch)
    resp = TestClient(main.app).post("/api/lexical/refresh")
    assert resp.status_code == 200
    assert resp.json()["reopened"] is True
    assert reopens == ["refresh requested"]


def test_in_process_ingestion_moves_the_stamp_instead_of_reopening(monkeypatch):
    monkeypatch.setattr(main, "chroma_collection", FakeCollection(CANNED))
    monkeypatch.setattr(main, "model", FakeModel())
    monkeypatch.setattr(main, "_chroma_stamp_seen", ("before",))
    monkeypatch.setattr(main, "_chroma_write_stamp", lambda db_path=None: ("after",))
    monkeypatch.setattr(main, "_build_lexical_index", lambda: None)
    seen_during = {}

    def fake_index_vault(collection, model, incremental=True, log=print):
        seen_during["ingesting"] = main._ingesting
        return {"files_scanned": 1, "files_reindexed": 1, "files_skipped": 0,
                "files_pruned": 0, "chunks_written": 2, "batches_failed": 0}

    monkeypatch.setattr(main.indexer, "index_vault", fake_index_vault)
    main.run_ingestion_sync()
    assert seen_during == {"ingesting": True}
    assert main._ingesting is False
    assert main._chroma_stamp_seen == ("after",)


# ── against real Chroma: the failure mode and the recovery ────────────────

def _tiny_store(path):
    client = chromadb.PersistentClient(path=str(path))
    coll = client.get_or_create_collection("second_brain")
    coll.add(
        ids=["n1", "n2", "c1"],
        embeddings=[[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]],
        documents=["note one", "note two", "chat one"],
        metadatas=[
            {"source": "n1.md", "title": "N1", "category": "note"},
            {"source": "n2.md", "title": "N2", "category": "note"},
            {"source": "c1.md", "title": "C1", "category": "chat"},
        ],
    )
    return client, coll


# What the nightly indexer does to the store from its own process: drop a
# note's chunks and write replacements plus something new.
WRITER = textwrap.dedent("""
    import sys, chromadb
    coll = chromadb.PersistentClient(path=sys.argv[1]).get_collection("second_brain")
    coll.delete(ids=["n2"])
    coll.add(ids=["n3"], embeddings=[[0, 1, 0, 0]], documents=["note three"],
             metadatas=[{"source": "n3.md", "title": "N3", "category": "note"}])
""")


def test_write_stamp_moves_on_writes_not_on_opens(tmp_path):
    client, _ = _tiny_store(tmp_path)
    before = main._chroma_write_stamp(str(tmp_path))
    assert before  # non-empty once the collection has segments
    client.close()

    reopened = chromadb.PersistentClient(path=str(tmp_path))
    coll = reopened.get_collection("second_brain")
    assert coll.count() == 3
    assert main._chroma_write_stamp(str(tmp_path)) == before  # a bare open does not move it
    coll.add(ids=["n9"], embeddings=[[0, 0, 0, 1]], documents=["x"],
             metadatas=[{"source": "n9.md", "title": "N9", "category": "note"}])
    assert main._chroma_write_stamp(str(tmp_path)) != before
    reopened.close()


def test_write_stamp_is_none_without_a_store(tmp_path):
    assert main._chroma_write_stamp(str(tmp_path / "nowhere")) is None


def test_reopen_picks_up_writes_from_another_process(tmp_path, monkeypatch):
    client, coll = _tiny_store(tmp_path)
    monkeypatch.setattr(main.config, "get_chroma_path", lambda: str(tmp_path))
    monkeypatch.setattr(main, "chroma_client", client)
    monkeypatch.setattr(main, "chroma_collection", coll)
    monkeypatch.setattr(main, "_chroma_stamp_seen", main._chroma_write_stamp(str(tmp_path)))
    monkeypatch.setattr(main, "_chroma_generation", 0)
    monkeypatch.setattr(main, "_chroma_last_reopen", float("-inf"))
    monkeypatch.setattr(main, "_ingesting", False)
    builds = []
    monkeypatch.setattr(main, "_build_lexical_index", lambda: builds.append(1))
    assert main.ensure_chroma_fresh() is False  # nothing has been written yet

    subprocess.run([sys.executable, "-c", WRITER, str(tmp_path)],
                   check=True, capture_output=True, text=True, timeout=120)

    assert main.ensure_chroma_fresh() is True
    assert main._chroma_generation == 1
    assert builds == [1]
    fresh = main.chroma_collection
    assert fresh is not coll
    hits = fresh.query(query_embeddings=[[0, 1, 0, 0]], n_results=2, where={"category": "note"})
    assert "n3" in hits["ids"][0]
    assert "n2" not in hits["ids"][0]
    assert main.ensure_chroma_fresh() is False  # and the new stamp is recorded
    main.chroma_client.close()
