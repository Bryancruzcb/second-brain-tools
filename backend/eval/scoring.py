"""Pure scoring functions for the retrieval eval. No I/O, no Chroma.

Metrics are note-level: chunk candidates are deduped to unique note paths
first (unique_sources), then rank = 1-based position of the first expected
note. This mirrors what the app does — Qwen sees the notes behind the top-k
chunks, so a note whose chunks fill positions 1-3 is one result, not three.
"""


def unique_sources(candidates):
    """Ordered unique note paths from chunk-level candidates (best first)."""
    seen = []
    for candidate in candidates:
        source = candidate["source"]
        if source not in seen:
            seen.append(source)
    return seen


def score_case(retrieved_sources, expected_sources, k=4):
    """Score one case. retrieved_sources: ordered unique note paths.

    Returns {"hit": bool, "reciprocal_rank": float, "rank": int | None},
    rank being the 1-based position of the first expected source within the
    top k, or None on a miss.
    """
    expected = set(expected_sources)
    for i, source in enumerate(retrieved_sources[:k], start=1):
        if source in expected:
            return {"hit": True, "reciprocal_rank": 1.0 / i, "rank": i}
    return {"hit": False, "reciprocal_rank": 0.0, "rank": None}


def aggregate(case_results):
    """Mean hit-rate and MRR over gradable cases; zeros when empty."""
    if not case_results:
        return {"hit_rate": 0.0, "mrr": 0.0, "cases": 0}
    hits = sum(1 for r in case_results if r["hit"])
    mrr = sum(r["reciprocal_rank"] for r in case_results) / len(case_results)
    return {"hit_rate": hits / len(case_results), "mrr": mrr, "cases": len(case_results)}
