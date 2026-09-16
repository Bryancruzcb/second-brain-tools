"""Score a running service through GET /api/search, and print numbers only.

run_eval.py scores retrieval in this process against a local Chroma store.
That cannot be pointed at a pod: the store is on the node's volume and the
only way in is the HTTP API. This mode asks the service the same questions
over the network and scores what it serves with the same score_case, so the
gate measures the thing users would get, rerankers and dedupe included.

Two consequences follow from scoring over HTTP, and they are why these
numbers get their own card (deploy/eval/cloud-scorecard.json) and are never
compared with backend/eval/scorecard.json:

- /api/search dedupes by title and returns only the served top k, so the
  deep pool the in-process eval inspects is not visible here.
- The cloud index is the vault minus whatever the sync refused, so cases
  whose expected notes never left the desktop are ungradable rather than
  misses. Pass --vault-dir to detect them; without it every case is graded.

Nothing this prints may carry vault content. The questions travel in the
query string of a request, never into stdout: error lines name a case by
index, httpx exceptions are re-raised without their URL (which holds the
question), and the summary is checked with private_keys_found before it is
printed at all.

Usage, from backend/ or from the image:
    python -m eval.http_eval --api http://second-brain:8000 --dataset /data/dataset.jsonl
    python -m eval.http_eval ... --vault-dir /data/vault --scorecard /app/deploy/eval/cloud-scorecard.json
    python -m eval.http_eval ... --record /app/deploy/eval/cloud-scorecard.json
"""
import argparse
import datetime
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

import config
from eval.dataset import load_dataset
from eval.scorecard import drift_verdict, private_keys_found
from eval.scoring import aggregate, score_case

SEARCH_PATH = "/api/search"
RETRY_ATTEMPTS = 2
RETRY_PAUSE_S = 2.0

EXIT_DRIFT = 1
EXIT_REFUSED = 2


def search(client, base_url, question, scope):
    """The note paths /api/search serves for one question, best first.

    Raises RuntimeError naming only the exception type: httpx puts the
    request URL in its message, and the URL carries the question.
    """
    last = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = client.get(
                base_url.rstrip("/") + SEARCH_PATH,
                params={"q": question, "scope": scope},
            )
            response.raise_for_status()
            results = response.json().get("results", [])
            return [r["id"] for r in results]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            last = e
            if attempt + 1 < RETRY_ATTEMPTS:
                time.sleep(RETRY_PAUSE_S)
    raise RuntimeError(f"{type(last).__name__} from {SEARCH_PATH}")


def expected_present(expected_sources, vault_dir):
    """Did any expected note survive the sync into the cloud copy?

    The sync refuses a note with a credential in it, so the cloud index
    cannot contain it and no amount of retrieval quality would find it.
    That is a gap in the dataset for this environment, not a miss.
    """
    if vault_dir is None:
        return True
    return any(os.path.exists(os.path.join(vault_dir, s)) for s in expected_sources)


def score_cases(cases, *, client, base_url, k, vault_dir=None):
    """Ask every case and aggregate. Returns a summary of numbers only."""
    graded, ungradable, errors = [], 0, 0
    for index, case in enumerate(cases):
        if not expected_present(case["expected_sources"], vault_dir):
            ungradable += 1
            continue
        try:
            sources = search(client, base_url, case["question"], case["scope"])
        except RuntimeError as e:
            # The case is identified by position. Its text stays out of the log.
            print(f"case {index}: {e}", file=sys.stderr)
            errors += 1
            continue
        graded.append(score_case(sources, case["expected_sources"], k=k))

    summary = aggregate(graded)
    summary["k"] = k
    summary["ungradable"] = ungradable
    summary["errors"] = errors
    return summary


def dataset_fingerprint(path, cases):
    """Case count and content hash: enough to tell two datasets apart."""
    with open(path, "rb") as f:
        return {"cases": len(cases), "sha256": hashlib.sha256(f.read()).hexdigest()}


def build_cloud_scorecard(summary, *, dataset, recorded_at):
    """The card the gate compares against. Numbers, a date, and a hash."""
    return {
        "recorded_at": recorded_at,
        "measured_through": SEARCH_PATH,
        "dataset": dict(dataset),
        "metrics": {
            "k": summary["k"],
            "hit_rate": summary["hit_rate"],
            "mrr": summary["mrr"],
            "cases": summary["cases"],
            "ungradable": summary["ungradable"],
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Score a running API through /api/search")
    parser.add_argument("--api", default="http://localhost:8000",
                        help="base URL of the service to score")
    parser.add_argument("--dataset", required=True, help="private eval set (JSONL)")
    parser.add_argument("--k", type=int, default=config.get_top_k(),
                        help="cut for hit-rate and MRR; the service decides what it serves")
    parser.add_argument("--vault-dir", help="cloud copy of the vault; cases whose expected "
                                            "notes are missing from it count as ungradable")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--scorecard", help="compare with this card and fail on drift")
    parser.add_argument("--record", help="write this run to that path as the new card")
    args = parser.parse_args(argv)

    cases = load_dataset(args.dataset)
    # The timeout belongs to the client: one place, and it also covers the
    # connect phase when the pod is up but not yet serving.
    with httpx.Client(timeout=args.timeout) as client:
        summary = score_cases(cases, client=client, base_url=args.api, k=args.k,
                              vault_dir=args.vault_dir)

    # Fail closed: nothing is printed until the summary is known to be clean.
    leaked = private_keys_found(summary)
    if leaked:
        print(f"REFUSING to print the summary: it carries {', '.join(leaked)}", file=sys.stderr)
        return EXIT_REFUSED
    print(json.dumps(summary, sort_keys=True))

    # A case that never reached the service is not a passing case. The gate
    # promotes on these numbers, so an unreachable pod must not read as 100%.
    if summary["errors"]:
        print(f"{summary['errors']} case(s) failed to reach the service", file=sys.stderr)
        return EXIT_REFUSED

    if args.record:
        card = build_cloud_scorecard(
            summary,
            dataset=dataset_fingerprint(args.dataset, cases),
            recorded_at=datetime.date.today().isoformat(),
        )
        with open(args.record, "w", encoding="utf-8") as f:
            json.dump(card, f, indent=2)
            f.write("\n")
        print(f"recorded {args.record}")

    if args.scorecard:
        with open(args.scorecard, "r", encoding="utf-8") as f:
            recorded = json.load(f)
        drifted, message = drift_verdict(
            summary["hit_rate"], recorded["metrics"]["hit_rate"], summary["cases"])
        print(message)
        if drifted:
            return EXIT_DRIFT
    return 0


if __name__ == "__main__":
    sys.exit(main())
