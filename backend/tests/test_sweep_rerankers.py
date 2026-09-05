"""Pure parts of the reranker sweep: scoring on frozen pools and the report."""
from eval import sweep_rerankers as sweep
from tests.fakes import OverlapCrossEncoder


def _chunk(cid, source, text):
    return {"id": cid, "source": source, "title": source, "chunk": text}


POOLS = {
    "depth": 4,
    "cases": [
        {
            "question": "alpha beta",
            "scope": "notes",
            "expected_sources": ["b.md"],
            # fused order puts the wrong note first; the overlap reranker
            # promotes b.md's chunks. Two b.md chunks sit at reranked 1-2, so
            # the served view at k=2 sees ONE unique note and the notes view
            # at k=2 sees two.
            "pool": [
                _chunk("a1", "a.md", "nothing here"),
                _chunk("b1", "b.md", "alpha beta gamma"),
                _chunk("b2", "b.md", "alpha beta"),
                _chunk("c1", "c.md", "alpha"),
            ],
        },
        {
            "question": "delta",
            "scope": "notes",
            "expected_sources": ["z.md"],
            "pool": [_chunk("a2", "a.md", "delta"), _chunk("c2", "c.md", "delta delta")],
        },
    ],
}


def test_score_pools_reports_served_and_notes_views():
    out = sweep.score_pools(POOLS, OverlapCrossEncoder(), ks=(1, 2, 3), rounds=1)
    m = out["metrics"]
    # Case 1: reranked chunk order is b1, b2, c1, a1 (overlap 2, 2, 1, 0).
    # Case 2: z.md is not in the pool at all -> miss everywhere.
    assert m["reranked_served"]["1"]["hit_rate"] == 0.5
    assert m["reranked_served"]["2"]["hit_rate"] == 0.5
    assert m["reranked_notes"]["1"]["hit_rate"] == 0.5
    # Fused order (a1 first) misses at k=1 and hits at k=2 in both views.
    assert m["fused_served"]["1"]["hit_rate"] == 0.0
    assert m["fused_served"]["2"]["hit_rate"] == 0.5
    assert m["reranked_served"]["1"]["mrr"] == 0.5
    assert m["fused_served"]["2"]["mrr"] == 0.25
    assert out["cases"] == 2
    assert out["pool_recall"] == 0.5


def test_score_pools_times_every_case_per_round_after_a_warmup():
    out = sweep.score_pools(POOLS, OverlapCrossEncoder(), ks=(1,), rounds=3)
    lat = out["latency_ms"]
    assert lat["n"] == 6 and len(lat["per_query"]) == 6
    assert set(lat) >= {"median", "p95", "mean", "min", "max", "per_query", "n"}
    assert all(v >= 0 for v in lat["per_query"])


def test_score_pools_records_per_case_ranks_without_question_text():
    out = sweep.score_pools(POOLS, OverlapCrossEncoder(), ks=(2,), rounds=1)
    rows = out["per_case"]
    assert rows[0] == {"case": 0, "in_pool": True, "fused_chunk_rank": 2,
                       "reranked_chunk_rank": 1, "reranked_note_rank": 1}
    assert rows[1] == {"case": 1, "in_pool": False, "fused_chunk_rank": None,
                       "reranked_chunk_rank": None, "reranked_note_rank": None}
    assert "question" not in rows[0]


def test_report_pools_latency_across_rounds_and_keeps_metrics():
    r1 = {"model": "m", "max_length": 512, "params_m": 22.7, "depth": 4, "cases": 2,
          "metrics": {"reranked_served": {"4": {"hit_rate": 0.5, "mrr": 0.5}},
                      "reranked_notes": {"4": {"hit_rate": 0.5, "mrr": 0.5}},
                      "fused_served": {"4": {"hit_rate": 0.0, "mrr": 0.0}}},
          "latency_ms": {"per_query": [10.0, 30.0]}}
    r2 = dict(r1, latency_ms={"per_query": [20.0, 40.0]})
    rows = sweep.aggregate([r1, r2])
    assert len(rows) == 1
    row = rows[0]
    assert row["model"] == "m" and row["rounds"] == 2 and row["n_timed"] == 4
    assert row["median_ms"] == 25.0
    assert row["hit"]["reranked_served"]["4"] == 0.5
    table = sweep.render_table(rows, ks=(4,))
    assert "| m |" in table and "22.7" in table and "25" in table


def test_cap_per_source_keeps_order_and_limits_chunks_per_note():
    ranked = [_chunk("b1", "b.md", "x"), _chunk("b2", "b.md", "x"), _chunk("a1", "a.md", "x"),
              _chunk("b3", "b.md", "x"), _chunk("c1", "c.md", "x")]
    assert [c["id"] for c in sweep.cap_per_source(ranked, 1)] == ["b1", "a1", "c1"]
    assert [c["id"] for c in sweep.cap_per_source(ranked, 2)] == ["b1", "b2", "a1", "c1"]


def test_capped_views_reach_a_note_the_served_view_misses():
    # Three chunks tie on overlap, so the reranked order is the pool order:
    # two chunks of the wrong note w.md sit above the expected e.md chunk.
    pools = {"depth": 3, "cases": [{
        "question": "alpha", "scope": "notes", "expected_sources": ["e.md"],
        "pool": [_chunk("w1", "w.md", "alpha alpha"), _chunk("w2", "w.md", "alpha alpha"),
                 _chunk("e1", "e.md", "alpha")],
    }]}
    m = sweep.score_pools(pools, OverlapCrossEncoder(), ks=(2,), rounds=1)["metrics"]
    assert m["reranked_served"]["2"]["hit_rate"] == 0.0   # top-2 chunks are both w.md
    assert m["reranked_cap1"]["2"]["hit_rate"] == 1.0     # w1, e1
    assert m["reranked_cap2"]["2"]["hit_rate"] == 0.0     # w1, w2
    assert m["reranked_notes"]["2"]["hit_rate"] == 1.0    # w.md, e.md
