from eval.scoring import aggregate, score_case, unique_sources


def test_unique_sources_dedupes_preserving_order():
    candidates = [
        {"source": "a.md"}, {"source": "b.md"}, {"source": "a.md"}, {"source": "c.md"},
    ]
    assert unique_sources(candidates) == ["a.md", "b.md", "c.md"]


def test_hit_at_rank_one():
    result = score_case(["a.md", "b.md"], ["a.md"], k=4)
    assert result == {"hit": True, "reciprocal_rank": 1.0, "rank": 1}


def test_hit_at_rank_three():
    result = score_case(["x.md", "y.md", "a.md"], ["a.md"], k=4)
    assert result["hit"] is True
    assert result["reciprocal_rank"] == 1.0 / 3
    assert result["rank"] == 3


def test_miss_scores_zero():
    result = score_case(["x.md", "y.md"], ["a.md"], k=4)
    assert result == {"hit": False, "reciprocal_rank": 0.0, "rank": None}


def test_expected_source_beyond_k_is_a_miss():
    retrieved = ["1.md", "2.md", "3.md", "4.md", "a.md"]
    result = score_case(retrieved, ["a.md"], k=4)
    assert result["hit"] is False


def test_any_of_multiple_expected_sources_counts():
    result = score_case(["x.md", "b.md"], ["a.md", "b.md"], k=4)
    assert result["rank"] == 2


def test_aggregate_means():
    results = [
        {"hit": True, "reciprocal_rank": 1.0, "rank": 1},
        {"hit": True, "reciprocal_rank": 0.5, "rank": 2},
        {"hit": False, "reciprocal_rank": 0.0, "rank": None},
    ]
    agg = aggregate(results)
    assert agg["cases"] == 3
    assert agg["hit_rate"] == 2 / 3
    assert agg["mrr"] == (1.0 + 0.5 + 0.0) / 3


def test_aggregate_empty_is_zero():
    assert aggregate([]) == {"hit_rate": 0.0, "mrr": 0.0, "cases": 0}


def test_score_case_at_applies_k_to_chunks_before_deduping():
    from eval.scoring import score_case_at
    candidates = [{"source": s} for s in ["a.md", "a.md", "a.md", "a.md", "b.md", "c.md"]]
    scored = score_case_at(candidates, ["b.md"], ks=[4, 6])
    # Four chunks all from a.md: a k=4 run never showed b.md, so it is a miss
    # there even though b.md is the second unique note overall.
    assert scored[4] == {"hit": False, "reciprocal_rank": 0.0, "rank": None}
    assert scored[6] == {"hit": True, "reciprocal_rank": 0.5, "rank": 2}
