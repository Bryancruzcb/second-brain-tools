"""Score the current retrieval pipeline against the eval dataset.

Usage (from backend/, venv active):
    python -m eval.run_eval             # uses eval/dataset.jsonl
    python -m eval.run_eval --dataset path/to/other.jsonl --k 4

The dataset is private and gitignored; copy dataset.example.jsonl to
dataset.jsonl and replace it with real cases about your own vault.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import retrieval
from eval.dataset import load_dataset
from eval.scoring import aggregate, score_case, unique_sources

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATASET = os.path.join(EVAL_DIR, "dataset.jsonl")
RESULTS_PATH = os.path.join(EVAL_DIR, "results.json")


def run(cases, *, model, collection, lexical=None, cross_encoder=None, k=retrieval.TOP_K):
    """Score every case. Returns (per_case_rows, summary).

    A case whose expected sources are entirely absent from the index is
    "ungradable" (stale dataset entry) and excluded from the averages.

    Each row records the notes actually retrieved, so a miss can be diagnosed
    from results.json instead of by rerunning the query by hand.
    """
    rows = []
    gradable = []
    for case in cases:
        expected = case["expected_sources"]
        present = collection.get(where={"source": {"$in": expected}}, include=[])
        if not (present.get("ids") or []):
            rows.append({"question": case["question"], "status": "ungradable",
                         "rank": None, "expected_sources": expected,
                         "retrieved": []})
            continue

        candidates = retrieval.retrieve_hybrid(
            case["question"], model=model, collection=collection,
            lexical=lexical, cross_encoder=cross_encoder, scope=case["scope"], k=k,
        )
        retrieved = unique_sources(candidates)
        result = score_case(retrieved, expected, k=k)
        gradable.append(result)
        rows.append({"question": case["question"],
                     "status": "hit" if result["hit"] else "miss",
                     "rank": result["rank"], "expected_sources": expected,
                     "retrieved": retrieved})

    summary = aggregate(gradable)
    summary["ungradable"] = sum(1 for r in rows if r["status"] == "ungradable")
    summary["k"] = k
    return rows, summary


def main():
    parser = argparse.ArgumentParser(description="Retrieval eval: hit-rate@k and MRR@k")
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--k", type=int, default=retrieval.TOP_K)
    args = parser.parse_args()

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
    model = SentenceTransformer(config.get_embedding_model())
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

    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "cases": rows}, f, indent=2)
    print(f"\nWrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()
