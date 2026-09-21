# The index looks old, or search gets worse while it rebuilds

Game-day scenario 3, which replays the real incident this repository already
had: the indexer writes the Chroma store from another process while the API
serves from it. Read `README.md` in this folder first if you do not know how
to reach the node.

## What you will see

One of three issues, and they mean different things.

`Alert: IndexerStale in <namespace>`, label `alert`, severity warning. The
nightly CronJob has not succeeded for over 26 hours, or was created that long
ago and has never succeeded (`deploy/monitoring/rules/second-brain.yml`).

`Alert: CanaryHitRateDropped in <namespace>`. The canary's hit rate has been
below its recorded baseline for two runs. Ten fixed questions every 15
minutes, so one miss moves it ten points.

`Alert: SearchLatencyHigh in <namespace>`. Search p95 above 3 seconds for 10
minutes.

In Grafana, on the "Second Brain API" dashboard: "Since the last successful
index run" is the panel that matches `IndexerStale`. "Index age (seen by the
API)" and "Chunks in the index" say what the serving process thinks it has.
"Canary hit rate" is drawn against its baseline, and "Search latency" carries
p50 and p95.

## What it means

The second writer is deliberate. The nightly CronJob rebuilds the index in its
own pod while the API keeps answering, and the API notices the store's write
stamp move and reopens its view, which is what PR #25 added; the indexer also
calls `/api/lexical/refresh` when it finishes
(`deploy/k8s/base/cronjob-indexer.yaml`, `backend/main.py`).

Two things look like a fault and are not. A climbing index age is not one: a
run over an unchanged vault writes nothing, and the vault only changes when
the desktop syncs, which is why the alert watches the CronJob's last success
instead of the age gauge. And a build making search worse is not one either.
On 2026-09-19 a full build ran search at p95 4.45 s and p50 2.61 s with the
node 72 percent busy, against p95 1.97 s and p50 1.72 s afterwards, because
the node's two vCPUs are one physical core and the embedding work and the
reranker share it; the canary scored 0.4 six minutes into the 22-minute first
build and 10 of 10 once it finished (`deploy/monitoring/README.md`).
`SearchLatencyHigh` went pending during that build and cleared by itself.

What is not broken: the notes. The cloud copy is a copy of a vault that lives
on the desktop and in S3, and the pods run with `READ_ONLY=1`, so nothing here
can change a note.

## Check

1. Which of the three it is, from the dashboard:

        python deploy/ops.py tunnel --to grafana     # then http://localhost:3000

   "Since the last successful index run" over 26 hours is a job that is not
   running. A canary dip with "Chunks in the index" moving is a build in
   progress. A canary dip with nothing moving is something else, and
   `bad-deploy.md` is the next runbook.

2. Ask the serving process what it has, in a second window:

        python deploy/ops.py tunnel --to prod --local-port 8001
        curl.exe "http://localhost:8001/api/ready?strict=1"
        curl.exe http://localhost:8001/metrics

   `/api/ready?strict=1` answers 200 with `"index_populated": true` when the
   collection holds chunks. In `/metrics`, `second_brain_collection_chunks`
   is what this process is serving and `second_brain_index_age_seconds` is
   how long since it last saw the store change (`backend/metrics.py`).

3. Did the desktop sync? A cloud index can be current with a vault copy that
   is not. `deploy/sync/sync_vault.py` runs on this desktop, and a dry run
   reads the vault, prints counts and uploads nothing
   (`deploy/README.md`):

        python deploy/sync/sync_vault.py --dry-run

4. Did the image change recently?

        python deploy/ops.py deploys

## Fix

**If the API's view is behind, make it reopen.** Through the tunnel:

    curl.exe -X POST http://localhost:8001/api/lexical/refresh

It reopens the store from disk, rebuilds the lexical index and answers with
the chunk count and whether it reopened. This is not one of the routes
`READ_ONLY` refuses, so it works against the cloud pods.

**If the index itself is old, run the indexer now:**

    python deploy/pipeline/send_command.py --sha <40-hex commit> --timeout 3000       --script deploy/pipeline/reindex.sh -- prod

It creates a Job from the indexer CronJob, waits, and prints how long it took
and whether it succeeded. It refuses to start while another indexer Job is
active in that namespace, because two writers on one volume is the condition
behind `docs/ops/postmortem-stale-index.md`. It prints the Job's exit and not
the indexer's log, which names the files it read.

Two things it is not. `POST /api/index` returns 403, because pods run with
`READ_ONLY=1` (`deploy/k8s/base/configmap.yaml`). And `deploy-namespace.sh`
creates its one-off `indexer-first` Job only when the Deployment has no ready
replica, so on a namespace whose API is already serving, a deploy re-applies
and skips the indexer (`deploy/pipeline/README.md`).

**If the indexer is failing rather than sleeping**, start with

    python deploy/pipeline/send_command.py --sha <40-hex commit> --timeout 300       --script deploy/pipeline/status.sh -- prod

which prints each Job's success and failure counts and the container exit
codes on pods that are not Running. The indexer's own log stays on the node:
it names the files it read, so nothing prints it here. What can be ruled out
from the status alone: a full disk, which has its own runbook
(`disk-almost-full.md`) and is the common cause, since the volume and the
build both live on the node's root disk; and a bad image, since the indexer
runs the same image as the API, so a rollback moves both (`bad-deploy.md`).

**If the API is serving an empty index on a namespace that should have one**,
check `CHROMA_DB_PATH` in `deploy/k8s/base/configmap.yaml`. With it unset or
wrong the backend quietly creates an empty index beside `main.py` and serves
empty results with no error, which is why it is pinned there.

## Verify

`second_brain_index_age_seconds` in `/metrics` drops after a reopen, and
"Chunks in the index" shows what you expect. After a successful run, "Since
the last successful index run" resets and `IndexerStale` closes. "Canary hit
rate" returns to its baseline within a couple of runs, one every 15 minutes;
the baseline card is `deploy/k8s/base/canary-card.json`. Latency is the last to settle: it comes
back on its own when a build ends, which is what the 2026-09-19 numbers above
showed.

## If it keeps happening

- The thresholds and the reasoning behind them:
  `deploy/monitoring/rules/second-brain.yml` and the table in
  `deploy/monitoring/README.md`. `IndexerStale` is a duration in seconds in
  the rule's expression; `CanaryHitRateDropped` is its `for:`.
- Latency alerting on every nightly build is the rule's `for:` or the build's
  schedule, not a bug: `deploy/monitoring/rules/second-brain.yml` and
  `deploy/k8s/base/cronjob-indexer.yaml`, which also says why 06:00 UTC.
- Both namespaces rebuild at once, and `deploy/k8s/README.md`, "Known
  follow-ups", already says prod's schedule should move later if the nightly
  run grows.
- If the nightly run keeps arriving stale rather than failing, the vault copy
  in S3 is the suspect, not the Job: the indexer reads what the desktop's sync
  last uploaded, and `IndexerStale` watches the Job rather than the data
  (`docs/ops/postmortem-stale-index.md`, "What is still true").
