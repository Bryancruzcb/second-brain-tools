# Cloud scorecard

`cloud-scorecard.json` is the number the delivery gate compares each deploy
against. It is not in git yet: it gets recorded from the first staging run,
because it can only be measured against a cluster serving the synced vault.

Record it, from inside the cluster:

    python -m eval.http_eval \
      --api http://second-brain.staging.svc.cluster.local:8000 \
      --dataset /data/dataset.jsonl --vault-dir /data/vault \
      --record /app/deploy/eval/cloud-scorecard.json

and commit the result. The file holds a date, the dataset's case count and
hash, and hit-rate, MRR, case counts at one k. It carries no question, no
note path and no snippet, which is why it can live in a public repo.

These numbers are **not** comparable with `backend/eval/scorecard.json`.
That one scores retrieval in process against the whole local index;
this one scores what `/api/search` serves from the cloud copy, which is
the vault minus every file the sync refused, deduped by title and cut to
the served top k. Two cards, two populations. A retrieval change that is
meant to move the numbers re-records this one against staging on purpose;
`drift_verdict` blocks promotion on a drop of 5 points or more otherwise.
