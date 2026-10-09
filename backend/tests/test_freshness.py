"""Freshness: the health cache (Map, Recent, Repair) must follow the index.

The index is rebuilt out of process (nightly / every few hours) but the health
cache was only rebuilt by a manual scan, so in Oct 2026 Recent and Map showed
the vault as of early September (320 notes against 900 indexed).
"""
from fastapi.testclient import TestClient

import main

# Captured before the conftest fixture stubs it out for every test.
_real_start_health_scan = main.start_health_scan


class _Store:
    def __init__(self, metadatas):
        self.metadatas = metadatas

    def count(self):
        return len(self.metadatas)

    def get(self, include=None, where=None):
        return {"metadatas": self.metadatas}


def _chunks(*pairs):
    return [{"source": s, "mtime": m} for s, m in pairs]


def _arm(monkeypatch, metadatas, nodes, scanned_at):
    monkeypatch.setattr(main, "chroma_collection", _Store(metadatas))
    monkeypatch.setattr(main, "_chroma_stamp_seen", None)  # no real store: no caching
    monkeypatch.setattr(main, "chroma_client", None)
    monkeypatch.setattr(main, "health_cache", {"nodes": [{"id": n} for n in nodes]})
    monkeypatch.setattr(main, "last_scan_time", scanned_at)
    monkeypatch.setattr(main, "is_scanning", False)


def test_index_freshness_counts_sources_and_newest_mtime(monkeypatch):
    _arm(monkeypatch, _chunks(("a.md", 10.0), ("a.md", 10.0), ("b.md", 30.0)), [], 0.0)
    assert main.index_freshness() == {"indexed_notes": 2, "newest_note_mtime": 30.0}


def test_index_freshness_survives_an_unreadable_store(monkeypatch):
    _arm(monkeypatch, [], [], 0.0)
    monkeypatch.setattr(main, "chroma_collection", object())  # no .get()
    assert main.index_freshness() == {"indexed_notes": None, "newest_note_mtime": None}
    assert main.health_cache_stale() is False


def test_cache_is_stale_when_the_index_has_more_notes(monkeypatch):
    _arm(monkeypatch, _chunks(("a.md", 10.0), ("b.md", 20.0)), ["a.md"], 100.0)
    assert main.health_cache_stale() is True


def test_cache_is_stale_when_the_index_holds_a_note_newer_than_the_scan(monkeypatch):
    _arm(monkeypatch, _chunks(("a.md", 10.0), ("b.md", 200.0)), ["a.md", "b.md"], 100.0)
    assert main.health_cache_stale() is True


def test_cache_is_fresh_after_a_scan_that_saw_every_note(monkeypatch):
    _arm(monkeypatch, _chunks(("a.md", 10.0), ("b.md", 20.0)), ["a.md", "b.md"], 100.0)
    assert main.health_cache_stale() is False


def test_ready_and_health_expose_freshness(monkeypatch):
    _arm(monkeypatch, _chunks(("a.md", 10.0), ("b.md", 20.0)), ["a.md"], 100.0)
    client = TestClient(main.app)
    fresh = client.get("/api/ready").json()["freshness"]
    assert fresh["indexed_notes"] == 2
    assert fresh["newest_indexed_note_mtime"] == 20.0
    assert fresh["health_scanned_at"] == 100.0
    assert fresh["health_notes"] == 1
    assert fresh["health_stale"] is True
    assert client.get("/api/health").json()["freshness"] == fresh


def test_refresh_rescans_the_health_cache_when_it_lags(monkeypatch):
    _arm(monkeypatch, _chunks(("a.md", 10.0), ("b.md", 20.0)), ["a.md"], 100.0)
    monkeypatch.setattr(main, "_build_lexical_index", lambda: None)
    reasons = []
    monkeypatch.setattr(main, "start_health_scan", lambda reason: reasons.append(reason) or True)
    resp = TestClient(main.app).post("/api/lexical/refresh")
    assert resp.status_code == 200
    assert resp.json()["health_scan_started"] is True
    assert len(reasons) == 1


def test_refresh_leaves_a_current_cache_alone(monkeypatch):
    _arm(monkeypatch, _chunks(("a.md", 10.0)), ["a.md"], 100.0)
    monkeypatch.setattr(main, "_build_lexical_index", lambda: None)
    monkeypatch.setattr(main, "start_health_scan",
                        lambda reason: (_ for _ in ()).throw(AssertionError("no scan expected")))
    resp = TestClient(main.app).post("/api/lexical/refresh")
    assert resp.json()["health_scan_started"] is False


def test_start_health_scan_runs_once_at_a_time(monkeypatch):
    monkeypatch.setattr(main, "is_scanning", False)
    ran = []
    monkeypatch.setattr(main, "run_health_scan_sync", lambda: ran.append(True))
    started = []

    class _Thread:
        def __init__(self, target, name=None, daemon=None):
            self.target = target

        def start(self):
            started.append(self.target)

    monkeypatch.setattr(main.threading, "Thread", _Thread)
    assert _real_start_health_scan("first") is True
    assert _real_start_health_scan("second") is False  # still marked scanning
    assert len(started) == 1
    started[0]()
    assert ran == [True]
