# Game day

Four scripted failures, run on purpose against a live node, each one timed
(docs/ops/PLAN.md section 6.6). The point is not that the system survives
them. The point is the numbers: how long the API was gone, how long before
an alert said so, how long the fix took, and whether the alert cleared by
itself afterwards.

    lib.sh              shared helpers: Prometheus, the API, polling, the result row
    01-kill-pod.sh      delete the API pod and time the restart
    02-fill-disk.sh     fill the root volume, wait for the alert, give the space back
    03-stale-index.sh   rebuild the index while the API serves
    04-bad-config.sh    break retrieval and check the gate refuses to promote it
    results.tsv         one row per run

## What the runs found

The game day ran from 2026-09-21 to 2026-09-23 on one node. `results.tsv`
has every run, including the one that went wrong and the one that measured
nothing.

- **01-kill-pod**, prod, three runs. The API was back in 20 to 21 s each
  time. `ApiNotReady` went pending in two runs and never fired, which is
  what PLAN.md expects.
- **02-fill-disk**, four runs. The first aimed at 95 percent, landed on the
  kubelet's eviction line and took both APIs and Grafana down for about six
  minutes (the table under its section). The script now aims at 83 percent,
  and the three runs after that all behaved the same: `DiskAlmostFull`
  pending at 45 to 60 s, firing at 646 to 661 s (600 of them are the alert's
  `for:`), and cleared by itself about a minute after the filler went.
- **03-stale-index**, staging, two runs, not three. The first had nothing to
  index. The second followed a vault sync of 56 changed notes: the indexer
  added 409 chunks in 181 s, the API's index age dropped to 0 while the Job
  was still writing, so PR #25's reopen held, and the canary stayed at 1.00
  with no readiness check failing. Its section says why a third run needs
  another sync.
- **04-bad-config**, staging, three runs. The gate refused `TOP_K=1` every
  time (`run-job.sh` exit 1, `drift`), and the namespace was serving
  `TOP_K=8` again 17 s after the restore started.

The numbers quoted in the sections below that are not in `results.tsv` are
week 3's, from `deploy/monitoring/README.md` and `deploy/k8s/README.md`.

## Running one

These run on the node as root, the same way every deploy step does
(`deploy/pipeline/README.md`). SSM's `AWS-RunShellScript` runs commands with
`sh`, which on Ubuntu is dash and stops on `set -o pipefail`, so
`send_command.py` invokes each script with `bash` and every script here is
bash:

    python deploy/pipeline/send_command.py --sha $SHA --timeout 900 \
      --script deploy/gameday/01-kill-pod.sh -- staging

    python deploy/pipeline/send_command.py --sha $SHA --timeout 1800 \
      --script deploy/gameday/02-fill-disk.sh --

    python deploy/pipeline/send_command.py --sha $SHA --timeout 4200 \
      --script deploy/gameday/03-stale-index.sh -- staging

    python deploy/pipeline/send_command.py --sha $SHA --timeout 4200 \
      --script deploy/gameday/04-bad-config.sh -- staging

`--timeout` is SSM's execution timeout and has to be longer than the script's
own waits, or SSM kills the command while it is still waiting and the exit
code says nothing. The numbers above are each script's worst case plus room:
01 watches for 420 s, 02 for 900 s plus 300 s of clearing, 03 gives the
rebuild 2,700 s and then samples for another 600, and 04 waits out two
rollouts and a gate Job that run-job.sh allows 1,800 s.

On the node itself, with `kubectl` already on `KUBECONFIG`:

    bash /opt/sbt/deploy/gameday/01-kill-pod.sh staging

Run each scenario three times, as PLAN.md asks, and paste all three rows.

## How these reach Prometheus

The in-cluster address
`http://prometheus-server.monitoring.svc.cluster.local:80` is the one every
pod uses and the one these scripts cannot use: they run on the node's host
network, where cluster DNS does not resolve. What works from the host is the
Service's ClusterIP, because k3s programs the service range into the host's
iptables. So `prom_init` in `lib.sh` reads the ClusterIP with kubectl and
curls `/api/v1/` on it:

    P=$(kubectl -n monitoring get svc prometheus-server -o jsonpath='{.spec.clusterIP}')
    curl -s --get "http://$P/api/v1/query" --data-urlencode "query=$EXPR"

That is not a new idea here. It is exactly what week 3's working scripts did
when they read Prometheus from the node during the first live run
(`monitoring-status.sh`, `latency.sh` and `grafana-check.sh` in the staging
scratch folder on the desktop). Each namespace's API is reached the same way,
through its own Service's ClusterIP rather than through the pinned
10.43.0.80 and 10.43.0.81, so the helpers work in any namespace and cannot go
stale against `ops.py`'s table.

Alert states come from `/api/v1/alerts`, which lists active alerts only:
`pending`, `firing`, or absent. Absent is reported as `none`, and a
Prometheus that did not answer is reported as `unknown` and never counted as
cleared.

## What each one does

### 01-kill-pod.sh NAMESPACE

Deletes the API pod and watches for the replacement. One replica per
namespace means the namespace has no API at all until the new pod passes
`/api/ready?strict=1`, so this measures a real gap, not a rolling update.

`ApiNotReady` is `for: 5m`, and PLAN.md expects recovery in under a minute,
so the alert should go pending and never reach firing. That is the
expectation, not an assertion: the script watches for 420 seconds, which is
past the 5 minutes the alert needs plus four of Prometheus's 30-second
evaluation intervals, and reports both transitions. A firing alert makes the
run exit 1 and is the finding.

The alert and the recovery are sampled in the same loop, because waiting for
the pod first and then starting to watch would miss a pending that came and
went during the restart.

With a 30-second scrape and a 30-second evaluation interval, a gap of a few
tens of seconds may be too short for kube-state-metrics to record a scrape
where the Deployment had no available replica. `pending none` is a real
possible outcome, and it means the outage was shorter than the monitoring's
resolution, not that nothing happened. The recovery column is the one that
answers how long the API was gone.

The run refuses to start when `ApiNotReady` is already active: the transition
it wants to time has already happened, for some other reason.

### 02-fill-disk.sh

Fills the root volume to 83 percent with one filler file, waits for
`DiskAlmostFull` (80 percent, `for: 10m`), removes the filler and waits for
the alert to clear.

**Why 83 and not PLAN.md's 95.** The kubelet has lines of its own on this
disk, and they sit above the alert's. Read from the node's kubelet config on
2026-09-22 (k3s defaults):

| used | what happens |
|---|---|
| 80% | `DiskAlmostFull` goes pending, and fires after 10 minutes |
| 85% | the kubelet deletes unused container images until the disk is back at 80% |
| 95% | free space is under 5% and the kubelet evicts pods, taints the node `NoSchedule`, and keeps the taint for 5 minutes after the space comes back |

The first run aimed at 95 percent and landed exactly on the eviction line.
Within 20 seconds the kubelet evicted both API pods and Grafana; image GC
then pulled the disk back to 79 percent, so `DiskAlmostFull` was pending for
30 seconds and never fired. The APIs were down for about six minutes, and
`ApiNotReady` fired in both namespaces (#63, #64), which is the outage alert
doing its job for a real outage the game day caused. So the target sits
between the alert and image GC, and the script reads both kubelet lines live
and refuses a target at or past either of them.

The lesson for the runbook is the table: the alert gives five points of
warning before the kubelet starts quietly deleting images, and fifteen
before it starts evicting pods.

This is the scenario with a blast radius. The root volume holds k3s, the
images, both namespaces' local-path volumes with the vault copy and the
Chroma index, and Prometheus's data. Filled to 100 percent it takes k3s and
the SSM agent down with it, and an SSM agent that cannot run a command cannot
be told to clean up: the node would have to be destroyed and rebuilt.

**The margin.** The filler is sized from the real free space, never from a
guess. It targets 83 percent used, it never leaves less than **1 GiB** free
whatever that target works out to, and it refuses to allocate less than 256
MiB, which would be noise. It refuses to run at all when the volume is
already at or past the alert's own 80 percent line, or while an indexer Job
is running: a rebuild that runs out of space mid-write is a real corrupted
index, not an experiment. On the 30 GB root volume the 83 percent target
leaves about 5 GB, so the 1 GiB floor only takes over on a much smaller disk.
`df`'s Avail already excludes the blocks ext4 reserves for root, and so does
the `node_filesystem_avail_bytes` the alert reads, so the two agree and the
true floor is higher than the computed one.

The filler is removed from an `EXIT` trap, and from `INT` and `TERM` too,
because SSM signals the command when its execution timeout passes. If a run
is killed in a way that runs no trap at all, the cleanup is one command:

    rm -f /var/tmp/second-brain-gameday-filler

`fallocate` reserves the blocks without writing them, which is what `statfs`
and therefore node-exporter count; `dd` is the fallback for a filesystem that
cannot preallocate.

### 03-stale-index.sh NAMESPACE

Runs the indexer while the API serves. This is the incident this project
already had: a long-lived API process held a Chroma view that another process
wrote underneath it and went on serving the old one, fixed in PR #25 by
reopening the store when the write stamp moves. The nightly CronJob is that
second writer on purpose, so the run asks whether the reopen still holds and
what the rebuild costs the people querying while it happens.

It creates a one-off Job from `second-brain-indexer`, named
`gameday-index-<timestamp>` so three runs do not collide and so it is not
`indexer-first`, which `deploy-namespace.sh` treats as its own marker for an
empty volume. Every 60 seconds it samples the index-age gauge, the chunk
count, the canary's hit rate against its baseline, search p95 and
`/api/ready?strict=1`, and it keeps sampling for 600 seconds after the Job
finishes, because the p95 expression rates over 10 minutes and a sample taken
the moment the build ends still carries the build's slow queries.

**A run needs something to index.** The Job is incremental: its init
container syncs the vault from S3, and `rebuild_rag_index.py` runs without
`--full`, so it embeds only the notes that changed since the last write. The
run at 2026-09-23 19:30 had nothing new. The Job finished in 60 s, the chunk
count stayed at 5,941, the index age kept climbing, and nothing was measured.
That run also overlapped the third disk run, with the root volume at 83
percent. The run at 23:21 followed a desktop vault sync
(`deploy/sync/sync_vault.py`) that copied 56 changed notes, and it is the
real one. So every run starts with a sync that changes something, and three
comparable runs need three of them, or a `--full` variant of this script,
which does not exist yet.

Week 3 measured a first build of the whole vault at 22 minutes, with search
p95 at 4.45 s during and 1.97 s after, and `SearchLatencyHigh` going pending
and clearing by itself. An incremental run over a few dozen notes is not that
build and does not reproduce it: the real run finished in 181 s, no query
landed while it wrote, and `SearchLatencyHigh` never went pending.

Search p95 only moves if somebody is searching. Between deploys the only
traffic is the canary's ten questions every 15 minutes, so a quiet window
samples as `absent` rather than as a number. Nothing here generates queries:
a query string would have to come from somewhere, and the eval questions are
private.

A Job that succeeded is deleted at the end; one that failed is left, because
its pod is the only place to look at why. A run that times out leaves the Job
running on purpose: killing a rebuild halfway through to tidy up a
measurement is the wrong trade.

### 04-bad-config.sh NAMESPACE

Sets `TOP_K` to 1 in the `second-brain-config` ConfigMap, restarts the
Deployment so the pods read it, runs the eval gate exactly as the pipeline
runs it, and expects drift.

PLAN.md describes this as deploying a branch whose config breaks retrieval.
The branch is not needed: `TOP_K` is pinned at 8 in
`deploy/k8s/base/configmap.yaml` and every pod reads it through `envFrom` at
start, so patching the ConfigMap and restarting gives the same broken API on
the image already running and leaves nothing behind in git. One chunk per
query is far past `drift_verdict`'s five-point rule rather than near it.

The gate runs through `deploy/pipeline/run-job.sh`, so this measures the gate
the deploy actually uses. Its exit codes carry straight through:

| run-job.sh | outcome | means |
|---|---|---|
| 1 | `drift` | the gate blocked it, which is the expectation |
| 0 | `no-drift` | the gate passed a config serving one chunk, which is a finding |
| 2 | `gate-refused` | the summary tripped `private_keys_found` |
| 3 | `no-card` | there is no recorded scorecard to compare against |
| other | `gate-error` | a timeout, a failed init container, a bad argument |

**Exit 3 means no card.** The gate compares against `cloud-scorecard.json`,
which can only be measured against a cluster serving the synced vault. It was
recorded against live staging on 2026-09-21 with `ops.py
record-cloud-scorecard` (`deploy/k8s/base/cloud-scorecard.json`, commit
f1cf665), before the three runs in `results.tsv`. Without it this scenario
reports `no-card`, exits 1, and has not tested anything.

Restoring the ConfigMap is not optional, so it runs from an `EXIT` trap as
well as on the ordinary path, and the script refuses to start if it cannot
read the original value, because it could not put back what it never saw.
The last lines of a run print the key's value and the readiness code, which
is how a reader confirms the namespace is back.

Prefer staging. The gate exists to stop a bad image before prod, and a
restart in prod is a real outage of the thing the canary watches. The rolling
restart also brings up a second API pod before the first goes
(`maxUnavailable: 0`), which wants about 900 MiB free on the node, so not at
06:00 UTC when both indexers run.

PLAN.md's second half of this scenario, pushing the same image to prod by
hand, waiting for the canary alert and rolling back by the runbook, is
deliberately not scripted. It is the operator exercise the runbook is for.

## The result row

Each script ends by printing the header from `results.tsv` and one
tab-separated row under it. **The scripts never write the file.** The node's
checkout is thrown away after the run, so a row written there would go with
it; the operator copies the last line of the output into
`deploy/gameday/results.tsv` in the repository and commits it.

`lib.sh` reads the header out of `results.tsv` in the same checkout rather
than keeping its own copy, and refuses to print a row whose field count does
not match. A column added to the file without a matching field at the call
site stops the scenario instead of producing a row that lines up with
nothing.

| column | what it holds |
|---|---|
| `scenario` | `01-kill-pod`, `02-fill-disk`, `03-stale-index`, `04-bad-config` |
| `started_utc` | when the run began, which is what tells three runs of one scenario apart |
| `namespace` | `staging`, `prod`, or `-` for scenario 2, which is about the node |
| `sha` | the first 12 of the image tag the namespace is serving |
| `alert` | the alert this scenario watches, or `-` |
| `pending_s` | seconds from the injection to that alert first seen pending, or `none` |
| `firing_s` | seconds to firing, or `none` |
| `recovery_s` | seconds from the injection until the system was healthy again |
| `clear_s` | seconds from the injection until the alert was no longer active, or `none` |
| `outcome` | one word, below |
| `detail` | the numbers that do not deserve a column, as `key=value` pairs |

`recovery_s` means the same thing in all four: the API ready again after the
delete, the filler gone, the rebuild finished, the namespace serving its
original `TOP_K`.

Outcomes: `recovered`, `recovered-fired`, `not-recovered`, `cleared`,
`not-cleared`, `no-alert`, `indexed`, `indexed-degraded`, `indexed-unready`,
`index-failed`, `index-timeout`, `drift`, `no-drift`, `no-card`,
`gate-refused`, `gate-error`, `not-restored`.

Exit codes are the same everywhere: **0** the expectation held, **1** it did
not or the run refused to start, **2** a bad argument.

## What these may print

The repository is public and the vault is not. These print counts, seconds,
status words, alert names, HTTP codes, pod names and short SHAs, and nothing
else. `send_command.py` reads everything a script printed before printing any
of it (`deploy/pipeline/output_guard.py`) and prints none of it when a single
line names a `.md` file, is not plain ASCII, runs over 300 characters, or is
a JSON object carrying a string value.

That last rule is why **no scenario here prints an application pod's logs**.
`second-brain-config` sets `LOG_FORMAT=json`, so one ordinary log line is a
JSON object with string values, and it would take the whole step's output
down with it. Scenario 4 is the one exception by inheritance: `run-job.sh`
prints the gate pod's logs, which `http_eval` has already checked with
`private_keys_found` before printing.

The longest line these produce is scenario 3's result row, around 210
characters against the 300 limit. A `detail` column that grows much past that
would silence the whole step, so keep it to short `key=value` pairs.

## Nothing is timed by sleeping

Every measurement polls with a deadline, counts the elapsed seconds from a
recorded instant, and says what it gave up on when the deadline passes. The
`sleep` calls in these scripts are poll intervals, the same way
`run-job.sh` waits for a Job. An alert cannot fire sooner than its `for:`
duration, so a measured time-to-firing includes it: `DiskAlmostFull` at 630
seconds is 600 seconds of `for:` plus 30 of noticing, not a slow alert.
