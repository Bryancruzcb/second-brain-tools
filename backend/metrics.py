"""Prometheus metrics for the retrieval API.

One rule governs this file: **no metric name, label, or label value may
carry vault content.** The scrape endpoint is read by Prometheus, quoted by
alert emails, and drawn on dashboards, none of which are as private as the
notes. Labels here are latencies and counts; the HTTP metrics label the
route template (`/api/note/{note_ref}`), never the note.

The two latencies are histograms rather than gauges: a gauge holds the last
value it was given, so a scrape every 15 seconds would sample one query in
however many arrived and hide the slow ones. The alert this feeds is on p95
over 10 minutes, which needs buckets.
"""
from prometheus_client import Gauge, Histogram

# Boundaries chosen around the measured configuration: a reranked query runs
# ~0.9 s on the desktop CPU (2026-09-04 int8 ONNX measurement), and the alert
# fires when p95 stays above 1.5 s, so 1.5 is a bucket edge rather than a
# number interpolated between 1.0 and 2.5.
LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0, float("inf"))

RETRIEVAL_SECONDS = Histogram(
    "second_brain_retrieval_seconds",
    "Time spent in hybrid retrieval for one request, reranking included.",
    buckets=LATENCY_BUCKETS,
)

RERANK_SECONDS = Histogram(
    "second_brain_rerank_seconds",
    "Time the cross-encoder spent scoring one pool of candidates.",
    buckets=LATENCY_BUCKETS,
)

COLLECTION_CHUNKS = Gauge(
    "second_brain_collection_chunks",
    "Chunks in the Chroma collection this process is serving.",
)

INDEX_AGE_SECONDS = Gauge(
    "second_brain_index_age_seconds",
    "Seconds since this process last saw the Chroma store change on disk.",
)
