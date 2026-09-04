"""Score the current retrieval pipeline against the eval dataset.

Usage (from backend/, venv active):
    python -m eval.run_eval             # uses eval/dataset.jsonl
    python -m eval.run_eval --dataset path/to/other.jsonl --k 4
    python -m eval.run_eval --record    # also write eval/scorecard.json + README block
    python -m eval.run_eval --check     # nightly: compare with the scorecard, warn on drift

The dataset is private and gitignored; copy dataset.example.jsonl to
dataset.jsonl and replace it with real cases about your own vault.
"""
import argparse
import datetime
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import retrieval
from eval.dataset import load_dataset
from eval.scorecard import (
    append_history, build_scorecard, drift_verdict, effective_config,
    render_readme_block, replace_block,
)
from eval.scoring import aggregate, score_case_at, unique_sources

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATASET = os.path.join(EVAL_DIR, "dataset.jsonl")
RESULTS_PATH = os.path.join(EVAL_DIR, "results.json")
SCORECARD_PATH = os.path.join(EVAL_DIR, "scorecard.json")
HISTORY_PATH = os.path.join(EVAL_DIR, "history.jsonl")
README_PATH = os.path.join(os.path.dirname(os.path.dirname(EVAL_DIR)), "README.md")


def run(cases, *, model, collection, lexical=None, cross_encoder=None,
        k=retrieval.TOP_K, ks=None):
    """Score every case. Returns (per_case_rows, summary).

    A case whose expected sources are entirely absent from the index is
    "ungradable" (stale dataset entry) and excluded from the averages.

    Each row records the notes actually retrieved and whether an expected
    source reached the fused pool, so a miss can be diagnosed from
    results.json instead of by rerunning the query by hand.

    k is the primary cut the top-level numbers and the rows describe. Every
    k in ks (always including 4, for continuity with the README history, and
    k itself) is scored from the same retrieval under summary["by_k"].
    """
    ks = sorted(set(ks or ()) | {4, k})
    rows = []
    gradable = {kk: [] for kk in ks}
    for case in cases:
        expected = case["expected_sources"]
        present = collection.get(where={"source": {"$in": expected}}, include=[])
        if not (present.get("ids") or []):
            rows.append({"question": case["question"], "status": "ungradable",
                         "rank": None, "expected_sources": expected,
                         "retrieved": [], "expected_in_pool": None})
            continue

        # Was the expected note even in the pool the reranker saw? Separates a
        # rerankable miss from one first-stage retrieval never surfaced. Probed
        # here rather than in retrieval.py so the serving path stays untouched.
        pool = unique_sources(retrieval.retrieve_hybrid(
            case["question"], model=model, collection=collection,
            lexical=lexical, cross_encoder=None, scope=case["scope"],
            k=retrieval.RERANK_DEPTH,
        ))
        expected_in_pool = any(e in pool for e in expected)

        candidates = retrieval.retrieve_hybrid(
            case["question"], model=model, collection=collection,
            lexical=lexical, cross_encoder=cross_encoder, scope=case["scope"], k=max(ks),
        )
        scored = score_case_at(candidates, expected, ks)
        for kk in ks:
            gradable[kk].append(scored[kk])
        result = scored[k]
        rows.append({"question": case["question"],
                     "status": "hit" if result["hit"] else "miss",
                     "rank": result["rank"], "expected_sources": expected,
                     "retrieved": unique_sources(candidates[:k]),
                     "expected_in_pool": expected_in_pool})

    summary = aggregate(gradable[k])
    summary["ungradable"] = sum(1 for r in rows if r["status"] == "ungradable")
    summary["k"] = k
    summary["by_k"] = {}
    for kk in ks:
        agg = aggregate(gradable[kk])
        summary["by_k"][str(kk)] = {"hit_rate": agg["hit_rate"], "mrr": agg["mrr"]}
    return rows, summary


def index_census(collection):
    """Counts the scorecard publishes: chunks and files, split by category."""
    got = collection.get(include=["metadatas"])
    sources = {}
    for meta in got.get("metadatas") or []:
        meta = meta or {}
        source = meta.get("source")
        if source:
            sources.setdefault(source, meta.get("category", "note"))
    chats = sum(1 for category in sources.values() if category == "chat")
    return {
        "chunks": len(got.get("ids") or []),
        "sources": len(sources),
        "notes": len(sources) - chats,
        "chats": chats,
        "embedding_model_stamp": (collection.metadata or {}).get("embedding_model"),
    }


def dataset_fingerprint(path, cases):
    """Case count and content hash; enough to tell two datasets apart."""
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    return {"cases": len(cases), "sha256": digest}


def main():
    parser = argparse.ArgumentParser(description="Retrieval eval: hit-rate@k and MRR@k")
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--k", type=int, default=retrieval.TOP_K)
    parser.add_argument("--record", action="store_true",
                        help="after scoring, write eval/scorecard.json and refresh the README block")
    parser.add_argument("--check", action="store_true",
                        help="score at the scorecard's k, append eval/history.jsonl and warn on "
                             "drift; skips quietly when the dataset or the scorecard is absent")
    args = parser.parse_args()

    scorecard = None
    if args.check:
        missing = [name for name, path in (("dataset", args.dataset), ("scorecard", SCORECARD_PATH))
                   if not os.path.exists(path)]
        if missing:
            # Other machines have no private set; the nightly job must not fail there.
            print(f"Eval check skipped: no {' or '.join(missing)} on this machine.")
            return
        with open(SCORECARD_PATH, "r", encoding="utf-8") as f:
            scorecard = json.load(f)
        args.k = int(scorecard["metrics"]["k"])

    if not os.path.exists(args.dataset):
        print(f"No dataset at {args.dataset}.")
        print(f"Copy {os.path.join(EVAL_DIR, 'dataset.example.jsonl')} to dataset.jsonl "
              "and replace it with real cases.")
        sys.exit(1)

    cases = load_dataset(args.dataset)

    # Heavy imports deferred so `import eval.run_eval` stays cheap in tests.
    import chromadb
    from sentence_transformers import SentenceTransformer

    import config
    from lexical import LexicalIndex
    collection = chromadb.PersistentClient(path=config.get_chroma_path()).get_collection("second_brain")

    # Scoring queries from one model against chunks embedded by another
    # produces numbers that look real and mean nothing. Refuse rather than
    # publish them.
    configured_model = config.get_embedding_model()
    stamped_model = (collection.metadata or {}).get("embedding_model")
    if stamped_model and stamped_model != configured_model:
        print(f"Embedding model mismatch: index stamped '{stamped_model}' but EMBEDDING_MODEL "
              f"is '{configured_model}'. These scores would be meaningless — run "
              "scripts/rebuild_rag_index.py --full first.")
        sys.exit(1)
    if not stamped_model:
        print("WARNING: index has no embedding-model stamp; assuming it was built with "
              f"'{configured_model}'. Run scripts/rebuild_rag_index.py --full to stamp it.")

    model = SentenceTransformer(configured_model)
    lex = LexicalIndex.build(collection)  # same keyword leg the endpoints serve

    # Same reranker the endpoints serve, same kill switch (see main.py).
    reranker_name = config.get_reranker_model()
    cross_encoder = None
    if not config.reranker_disabled(reranker_name):
        from sentence_transformers import CrossEncoder
        cross_encoder = CrossEncoder(reranker_name)

    rows, summary = run(cases, model=model, collection=collection, lexical=lex,
                        cross_encoder=cross_encoder, k=args.k)

    for row in rows:
        mark = {"hit": "HIT ", "miss": "MISS", "ungradable": "N/A "}[row["status"]]
        rank = f"@{row['rank']}" if row["rank"] else "   "
        print(f"{mark} {rank:>3}  {row['question'][:70]}")
    print()
    print(f"cases: {summary['cases']} gradable, {summary['ungradable']} ungradable")
    print(f"hit-rate@{summary['k']}: {summary['hit_rate']:.1%}")
    print(f"MRR@{summary['k']}: {summary['mrr']:.3f}")
    for kk, row in summary["by_k"].items():
        if int(kk) != summary["k"]:
            print(f"hit-rate@{kk}: {row['hit_rate']:.1%}  MRR@{kk}: {row['mrr']:.3f}")

    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "cases": rows}, f, indent=2)
    print(f"\nWrote {RESULTS_PATH}")

    today = datetime.date.today().isoformat()
    if args.record:
        card = build_scorecard(
            config=effective_config(), index=index_census(collection),
            dataset=dataset_fingerprint(args.dataset, cases), summary=summary,
            recorded_at=today,
        )
        with open(SCORECARD_PATH, "w", encoding="utf-8") as f:
            json.dump(card, f, indent=2)
            f.write("\n")
        # newline="" keeps the README's own line endings on both read and write.
        with open(README_PATH, "r", encoding="utf-8", newline="") as f:
            readme = f.read()
        with open(README_PATH, "w", encoding="utf-8", newline="") as f:
            f.write(replace_block(readme, render_readme_block(card)))
        print(f"Recorded {SCORECARD_PATH} and refreshed the README block.")

    if args.check:
        drifted, message = drift_verdict(
            summary["hit_rate"], scorecard["metrics"]["hit_rate"], summary["cases"])
        append_history(HISTORY_PATH, {
            "date": today, "hit_rate": summary["hit_rate"], "mrr": summary["mrr"],
            "k": summary["k"], "chunks": collection.count(),
        })
        print(message)


if __name__ == "__main__":
    main()
