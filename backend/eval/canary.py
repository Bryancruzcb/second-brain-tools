"""The canary: a few eval questions every 15 minutes, pushed to Prometheus.

The deploy gate (http_eval.py) scores a new build once, against the whole
eval set. Between deploys nothing watched retrieval quality: a stale index or
a config change that loses notes would only show up as worse answers. The
canary asks a fixed sample of the same questions through the same
/api/search, scores them with the same score_case, and pushes the hit rate to
the Pushgateway, where an alert compares it with the rate recorded for the
same sample.

The sample is fixed (evenly spread over the set, the same cases every run),
so a change in hit rate means the service changed, not the questions. With
ten cases one miss moves it by ten points.

What it pushes is numbers only, like everything else the eval prints:

  second_brain_canary_hit_rate            only when every case reached the API
  second_brain_canary_baseline_hit_rate   only when a card for this dataset exists
  second_brain_canary_cases               cases graded this run
  second_brain_canary_errors              cases that never reached the API
  second_brain_canary_last_run_timestamp_seconds

A run where the API was unreachable pushes no hit rate: all-error runs score
zero, and an outage should raise the error alert, not the quality one.

Usage, in the cluster (the CronJob in deploy/k8s/base):
    python -m eval.canary --api http://second-brain:8000 --dataset /work/dataset.jsonl \\
        --vault-dir /data/vault --pushgateway http://pushgateway.monitoring.svc:9091 \\
        --namespace staging --card /etc/canary/canary-card.json
and once, from the desktop through `ops.py tunnel`, to record the card:
    python -m eval.canary --api http://localhost:8000 --dataset eval/dataset.jsonl \\
        --vault-dir <sync staging mirror> --record ../deploy/k8s/base/canary-card.json
"""
import argparse
import datetime
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

import config
from eval.dataset import load_dataset
from eval.http_eval import EXIT_REFUSED, build_cloud_scorecard, dataset_fingerprint, score_cases
from eval.scorecard import private_keys_found

CANARY_CASES = 10
JOB = "second-brain-canary"


def canary_cases(cases, n=CANARY_CASES):
    """n cases spread evenly over the set, the same ones on every run."""
    if n >= len(cases):
        return list(cases)
    step = len(cases) / n
    return [cases[int(i * step)] for i in range(n)]


def baseline_hit_rate(card, fingerprint):
    """The recorded hit rate, if the card was recorded on this sample.

    A card from a different dataset, or a different sample size, would
    compare different questions, so it counts as no card at all.
    """
    if not card:
        return None
    if card.get("dataset") != fingerprint:
        return None
    return card.get("metrics", {}).get("hit_rate")


def exposition(summary, *, baseline, now):
    """One run in the Prometheus text format. Numbers only."""
    gauges = [("second_brain_canary_cases", summary["cases"]),
              ("second_brain_canary_errors", summary["errors"]),
              ("second_brain_canary_last_run_timestamp_seconds", round(now, 3))]
    if summary["errors"] == 0:
        gauges.append(("second_brain_canary_hit_rate", summary["hit_rate"]))
        if baseline is not None:
            gauges.append(("second_brain_canary_baseline_hit_rate", baseline))
    lines = []
    for name, value in gauges:
        lines += [f"# TYPE {name} gauge", f"{name} {value}"]
    return "\n".join(lines) + "\n"


def push(client, gateway, namespace, body):
    """PUT replaces the whole group, so a gauge left out this run disappears."""
    url = f"{gateway.rstrip('/')}/metrics/job/{JOB}/namespace/{namespace}"
    response = client.put(url, content=body.encode("utf-8"),
                          headers={"Content-Type": "text/plain; version=0.0.4"})
    response.raise_for_status()


def read_card(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ask a fixed sample of eval questions and push the hit rate")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--dataset", required=True, help="private eval set (JSONL)")
    parser.add_argument("--cases", type=int, default=CANARY_CASES, help="sample size")
    parser.add_argument("--k", type=int, default=config.get_top_k())
    parser.add_argument("--vault-dir", help="cloud copy of the vault, as for http_eval")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--card", help="the recorded canary card; missing means no baseline")
    parser.add_argument("--record", help="write this run as the canary card instead of pushing")
    parser.add_argument("--pushgateway", help="Pushgateway base URL")
    parser.add_argument("--namespace", default="local", help="grouping label for the push")
    args = parser.parse_args(argv)

    cases = load_dataset(args.dataset)
    sample = canary_cases(cases, args.cases)
    fingerprint = dict(dataset_fingerprint(args.dataset, cases), canary_cases=len(sample))

    with httpx.Client(timeout=args.timeout) as client:
        summary = score_cases(sample, client=client, base_url=args.api, k=args.k,
                              vault_dir=args.vault_dir)

        leaked = private_keys_found(summary)
        if leaked:
            print(f"REFUSING to print or push: the summary carries {', '.join(leaked)}", file=sys.stderr)
            return EXIT_REFUSED
        print(json.dumps(summary, sort_keys=True))

        if args.record:
            if summary["errors"]:
                print("not recording a card from a run with errors", file=sys.stderr)
                return EXIT_REFUSED
            card = build_cloud_scorecard(summary, dataset=fingerprint,
                                         recorded_at=datetime.date.today().isoformat())
            with open(args.record, "w", encoding="utf-8") as f:
                json.dump(card, f, indent=2)
                f.write("\n")
            print(f"recorded {args.record}")
            return 0

        if args.pushgateway:
            baseline = baseline_hit_rate(read_card(args.card), fingerprint)
            push(client, args.pushgateway, args.namespace,
                 exposition(summary, baseline=baseline, now=time.time()))

    return EXIT_REFUSED if summary["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
