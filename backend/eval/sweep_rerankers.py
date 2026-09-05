"""Reranker sweep: build the candidate pools once, then score one model per process.

Why this shape. The eval harness loads the embedder, the BM25 corpus and a
reranker in one process. That is fine for one model, but holding two
rerankers at once ran the machine out of memory, and a latency measured
while another model process runs is noise. So:

  1. ``pools`` runs first-stage retrieval once at the given depth and dumps
     every eval case's fused candidate pool to JSON. The file holds private
     note text; ``backend/eval/sweeps/`` is gitignored for that reason.
  2. ``score`` loads exactly one cross-encoder, reranks every pool through
     ``retrieval.rerank`` (the shipped code path), and writes hit-rate and
     MRR at several k plus per-query rerank latency.
  3. ``report`` folds score files into one markdown table.

Several ways to count a hit are reported, because they differ by a case or
two on this corpus:

  * ``reranked_served``: unique notes among the top-k reranked *chunks*.
    This is what /api/query hands to Qwen and what ``run_eval`` scores.
  * ``reranked_notes``: the top-k unique *notes* of the whole reranked pool,
    the number a note-level result list would show.
  * ``reranked_cap1`` / ``reranked_cap2``: the served view after limiting
    each note to one or two chunks, i.e. what a per-note cap would serve.

``fused_served`` / ``fused_notes`` score the pool order itself, i.e. no
reranker, so every model is compared against the same floor.

Latency rule: run ``score --rounds 1`` in a fresh process per model and call
the models in an interleaved order (A, B, A, B, ...). The first case of each
process is a warm-up that is never timed, so whichever model runs first does
not absorb lazy-init cost.

Usage (from backend/, venv active, offline flags set):
    python -m eval.sweep_rerankers pools --depth 30 --out eval/sweeps/pools-depth30.json
    python -m eval.sweep_rerankers score --pools eval/sweeps/pools-depth30.json \
        --model cross-encoder/ms-marco-MiniLM-L-12-v2 --out eval/sweeps/L-12.r1.json
    python -m eval.sweep_rerankers report eval/sweeps/*.r*.json
"""
import argparse
import datetime as _dt
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval.dataset import load_dataset
from eval.scoring import score_case, unique_sources

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATASET = os.path.join(EVAL_DIR, "dataset.jsonl")
DEFAULT_KS = (4, 6, 8, 10)
VIEWS = ("reranked_served", "reranked_notes", "reranked_cap1", "reranked_cap2",
         "fused_served", "fused_notes")


def cap_per_source(candidates, cap):
    """Keep at most ``cap`` chunks per note, preserving order."""
    seen = {}
    out = []
    for c in candidates:
        n = seen.get(c["source"], 0)
        if n < cap:
            out.append(c)
            seen[c["source"]] = n + 1
    return out


# ── pools ───────────────────────────────────────────────────────────────────

def build_pools(dataset_path, depth):
    """First-stage retrieval for every case at ``depth``; no reranker."""
    # retrieval binds its depths at import, so set them before importing.
    os.environ["HYBRID_DEPTH"] = str(depth)
    os.environ["RERANK_DEPTH"] = str(depth)
    import chromadb
    from sentence_transformers import SentenceTransformer

    import config
    import retrieval
    from lexical import LexicalIndex

    cases = load_dataset(dataset_path)
    collection = chromadb.PersistentClient(path=config.get_chroma_path()).get_collection("second_brain")
    configured = config.get_embedding_model()
    stamped = (collection.metadata or {}).get("embedding_model")
    if stamped and stamped != configured:
        sys.exit(f"Embedding model mismatch: index stamped '{stamped}', configured '{configured}'.")
    model = SentenceTransformer(configured)
    lexical = LexicalIndex.build(collection)

    out = []
    for i, case in enumerate(cases):
        present = collection.get(where={"source": {"$in": case["expected_sources"]}}, include=[])
        if not (present.get("ids") or []):
            print(f"case {i}: expected sources absent from the index, skipped")
            continue
        fused = retrieval.retrieve_hybrid(
            case["question"], model=model, collection=collection, lexical=lexical,
            cross_encoder=None, scope=case["scope"], k=depth,
        )
        out.append({
            "question": case["question"], "scope": case["scope"],
            "expected_sources": case["expected_sources"],
            "pool": [{k: c[k] for k in ("id", "source", "title", "chunk")} for c in fused],
        })
    return {
        "built_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "depth": depth, "embedding_model": configured,
        "index_chunks": collection.count(), "cases": out,
    }


# ── score ───────────────────────────────────────────────────────────────────

def _first_rank(sources, expected):
    expected = set(expected)
    for i, s in enumerate(sources, start=1):
        if s in expected:
            return i
    return None


def score_pools(pools, cross_encoder, ks=DEFAULT_KS, rounds=1):
    """Rerank every pool with ``cross_encoder`` and score it. Pure: no I/O.

    Returns metrics per view and k, per-case ranks (by case index only, no
    question text), and the timed latency of every rerank call after one
    untimed warm-up. Ranks come from the first round; later rounds only add
    timing samples.
    """
    import retrieval

    cases = pools["cases"]
    per_view = {view: {k: [] for k in ks} for view in VIEWS}
    per_case = []
    latencies = []
    in_pool_count = 0

    if cases:
        retrieval.rerank(cases[0]["question"], cases[0]["pool"],
                         cross_encoder=cross_encoder, k=len(cases[0]["pool"]))

    for r in range(rounds):
        for i, case in enumerate(cases):
            pool, expected = case["pool"], case["expected_sources"]
            t0 = time.perf_counter()
            ranked = retrieval.rerank(case["question"], pool, cross_encoder=cross_encoder, k=len(pool))
            latencies.append((time.perf_counter() - t0) * 1000.0)
            if r:
                continue
            fused_sources = unique_sources(pool)
            ranked_sources = unique_sources(ranked)
            cap1, cap2 = cap_per_source(ranked, 1), cap_per_source(ranked, 2)
            in_pool = _first_rank(fused_sources, expected) is not None
            in_pool_count += in_pool
            for k in ks:
                per_view["reranked_served"][k].append(score_case(unique_sources(ranked[:k]), expected, k=k))
                per_view["reranked_notes"][k].append(score_case(ranked_sources, expected, k=k))
                per_view["reranked_cap1"][k].append(score_case(unique_sources(cap1[:k]), expected, k=k))
                per_view["reranked_cap2"][k].append(score_case(unique_sources(cap2[:k]), expected, k=k))
                per_view["fused_served"][k].append(score_case(unique_sources(pool[:k]), expected, k=k))
                per_view["fused_notes"][k].append(score_case(fused_sources, expected, k=k))
            per_case.append({
                "case": i, "in_pool": in_pool,
                "fused_chunk_rank": _first_rank([c["source"] for c in pool], expected),
                "reranked_chunk_rank": _first_rank([c["source"] for c in ranked], expected),
                "reranked_note_rank": _first_rank(ranked_sources, expected),
            })

    def agg(results):
        n = len(results)
        if not n:
            return {"hit_rate": 0.0, "mrr": 0.0}
        return {"hit_rate": sum(r["hit"] for r in results) / n,
                "mrr": sum(r["reciprocal_rank"] for r in results) / n}

    metrics = {view: {str(k): agg(per_view[view][k]) for k in ks} for view in VIEWS}
    return {
        "cases": len(cases),
        "pool_recall": (in_pool_count / len(cases)) if cases else 0.0,
        "ks": list(ks), "rounds": rounds,
        "metrics": metrics,
        "latency_ms": latency_stats(latencies),
        "per_case": per_case,
    }


def latency_stats(samples):
    if not samples:
        return {"n": 0, "per_query": []}
    s = sorted(samples)
    return {
        "n": len(s), "median": statistics.median(s),
        "p95": s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))],
        "mean": statistics.fmean(s), "min": s[0], "max": s[-1],
        "per_query": [round(x, 2) for x in samples],
    }


class OnnxCrossEncoder:
    """CrossEncoder stand-in over an ONNX export: predict(pairs) -> scores.

    onnxruntime is already in the venv as a chromadb dependency, so a
    quantised export of the same weights can be timed without optimum.
    Tokenisation mirrors sentence_transformers.CrossEncoder (pair input,
    padding, longest-first truncation at max_length).
    """

    def __init__(self, session, tokenizer, max_length=512):
        self.session = session
        self.tokenizer = tokenizer
        self.max_length = max_length
        self.input_names = [i.name for i in session.get_inputs()]

    @classmethod
    def from_hub(cls, model_name, onnx_file, max_length=512):
        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from transformers import AutoTokenizer
        path = hf_hub_download(model_name, onnx_file)
        session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        return cls(session, AutoTokenizer.from_pretrained(model_name), max_length)

    def predict(self, pairs, batch_size=32, **_):
        import numpy as np
        scores = []
        for i in range(0, len(pairs), batch_size):
            batch = pairs[i:i + batch_size]
            enc = self.tokenizer([q for q, _ in batch], [d for _, d in batch], padding=True,
                                 truncation=True, max_length=self.max_length, return_tensors="np")
            ids = np.asarray(enc["input_ids"], dtype=np.int64)
            feed = {}
            for name in self.input_names:
                feed[name] = np.asarray(enc[name], dtype=np.int64) if name in enc else np.zeros_like(ids)
            logits = np.asarray(self.session.run(None, feed)[0])
            scores.extend(float(x) for x in (logits[:, 0] if logits.ndim == 2 else logits.reshape(-1)))
        return scores


def load_cross_encoder(name, max_length, trust_remote_code=False, onnx_file=None):
    """One reranker for this process. Returns (encoder, params in millions or None)."""
    if onnx_file:
        return OnnxCrossEncoder.from_hub(name, onnx_file, max_length), None
    from sentence_transformers import CrossEncoder
    kwargs = {"max_length": max_length}
    if trust_remote_code:
        kwargs["trust_remote_code"] = True
    ce = CrossEncoder(name, **kwargs)
    params = sum(p.numel() for p in ce.model.parameters())
    return ce, params / 1e6


# ── report ──────────────────────────────────────────────────────────────────

def aggregate(results):
    """Fold score files by (model, max_length): metrics from the first file,
    latency samples pooled across every round."""
    groups = {}
    for res in results:
        key = (res["model"], res.get("max_length"))
        g = groups.setdefault(key, {"model": res["model"], "max_length": res.get("max_length"),
                                    "params_m": res.get("params_m"), "depth": res.get("depth"),
                                    "cases": res.get("cases"), "hit": {}, "mrr": {},
                                    "rounds": 0, "samples": []})
        if not g["hit"]:
            for view, by_k in res["metrics"].items():
                g["hit"][view] = {k: v["hit_rate"] for k, v in by_k.items()}
                g["mrr"][view] = {k: v["mrr"] for k, v in by_k.items()}
        g["rounds"] += 1
        g["samples"].extend(res["latency_ms"].get("per_query", []))
    rows = []
    for g in groups.values():
        stats = latency_stats(g.pop("samples"))
        g["n_timed"] = stats.get("n", 0)
        g["median_ms"] = stats.get("median")
        g["p95_ms"] = stats.get("p95")
        rows.append(g)
    rows.sort(key=lambda r: (-r["hit"].get("reranked_served", {}).get("4", 0), r["median_ms"] or 0))
    return rows


def render_table(rows, ks=DEFAULT_KS, views=("reranked_served", "reranked_notes")):
    ks = [str(k) for k in ks]
    short = {"reranked_served": "served", "reranked_notes": "notes",
             "reranked_cap1": "cap1", "reranked_cap2": "cap2",
             "fused_served": "fused", "fused_notes": "fused notes"}
    head = ["model", "params (M)", "max len"]
    for view in views:
        head += [f"hit@{k} {short.get(view, view)}" for k in ks]
    head += ["MRR@4 served", "median ms", "p95 ms", "timed", "rounds"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        cells = [r["model"], f"{r['params_m']:.1f}" if r.get("params_m") is not None else "",
                 str(r.get("max_length") or "")]
        for view in views:
            by_k = r["hit"].get(view, {})
            cells += [f"{100 * by_k.get(k, 0):.1f}%" for k in ks]
        cells += [f"{r['mrr'].get('reranked_served', {}).get('4', 0):.3f}",
                  f"{r['median_ms']:.0f}" if r.get("median_ms") is not None else "",
                  f"{r['p95_ms']:.0f}" if r.get("p95_ms") is not None else "",
                  str(r.get("n_timed", 0)), str(r.get("rounds", 0))]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────

def main(argv=None):
    parser = argparse.ArgumentParser(description="Reranker sweep on frozen candidate pools.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pools", help="dump fused candidate pools at a depth")
    p.add_argument("--dataset", default=DEFAULT_DATASET)
    p.add_argument("--depth", type=int, required=True)
    p.add_argument("--out", required=True)

    s = sub.add_parser("score", help="rerank dumped pools with one cross-encoder")
    s.add_argument("--pools", required=True)
    s.add_argument("--model", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--max-length", type=int, default=512)
    s.add_argument("--trust-remote-code", action="store_true")
    s.add_argument("--onnx-file", default=None,
                   help="score a cached ONNX export of --model instead, e.g. onnx/model_quint8_avx2.onnx")
    s.add_argument("--ks", default=",".join(map(str, DEFAULT_KS)))
    s.add_argument("--rounds", type=int, default=1)
    s.add_argument("--tag", default="")

    r = sub.add_parser("report", help="markdown table from score files")
    r.add_argument("files", nargs="+")
    r.add_argument("--ks", default="4,6,8")
    r.add_argument("--views", default="reranked_served,reranked_notes")

    args = parser.parse_args(argv)

    if args.cmd == "pools":
        pools = build_pools(args.dataset, args.depth)
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(pools, f)
        recall = sum(any(s in {c["source"] for c in case["pool"]} for s in case["expected_sources"])
                     for case in pools["cases"]) / max(1, len(pools["cases"]))
        print(f"{len(pools['cases'])} pools at depth {args.depth}, pool recall {recall:.1%}, "
              f"index {pools['index_chunks']} chunks -> {args.out}")
        return

    if args.cmd == "score":
        with open(args.pools, encoding="utf-8") as f:
            pools = json.load(f)
        t0 = time.perf_counter()
        ce, params_m = load_cross_encoder(args.model, args.max_length, args.trust_remote_code,
                                          onnx_file=args.onnx_file)
        load_s = time.perf_counter() - t0
        ks = tuple(int(k) for k in args.ks.split(","))
        out = score_pools(pools, ce, ks=ks, rounds=args.rounds)
        label = f"{args.model} [{args.onnx_file}]" if args.onnx_file else args.model
        out.update({"model": label, "params_m": params_m, "max_length": args.max_length,
                    "load_s": load_s, "depth": pools["depth"], "pools_file": os.path.basename(args.pools),
                    "tag": args.tag, "scored_at": _dt.datetime.now().isoformat(timespec="seconds")})
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)
        m = out["metrics"]
        size = f"{params_m:.1f}M" if params_m is not None else "onnx"
        print(f"{label} ({size}, max_len {args.max_length}, load {load_s:.1f}s): "
              + " ".join(f"served@{k} {100 * m['reranked_served'][str(k)]['hit_rate']:.1f}%" for k in ks)
              + f" | median {out['latency_ms']['median']:.0f} ms p95 {out['latency_ms']['p95']:.0f} ms "
              f"over {out['latency_ms']['n']} timed calls -> {args.out}")
        return

    if args.cmd == "report":
        results = []
        for path in args.files:
            with open(path, encoding="utf-8") as f:
                results.append(json.load(f))
        print(render_table(aggregate(results), ks=tuple(int(k) for k in args.ks.split(",")),
                           views=tuple(args.views.split(","))))


if __name__ == "__main__":
    main()
