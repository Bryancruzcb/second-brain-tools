# Pipeline

What a deploy runs on the node. Nothing in the cluster is reachable from the
internet, so `deploy.yml` never talks to the API server: it hands each step to
SSM Run Command with `send_command.py`, which puts `/opt/sbt` at the commit
being deployed and runs one of these scripts there as root.

    send_command.py        send one script to the node, wait, exit with its code
    output_guard.py        what a node script may print into a public log
    record_deploy.py       one DynamoDB item per deploy, from those numbers
    node_state.py          nightly: is a node running, and should it be
    deploy-namespace.sh    pin the tag, apply, bootstrap an empty volume, wait
    run-job.sh             run the gate Job or the smoke Job and report
    rollback.sh            undo one Deployment and name the tag it landed on
    status.sh              read-only: what a namespace looks like right now
    reindex.sh             run the indexer once against a namespace that serves

The first four run on the GitHub runner; the three shell scripts run on the
node.

## What may be printed

`send_command.py` checks everything a script printed before printing any of
it (`output_guard.py`), because a public workflow log cannot be taken back.
A line is refused when it is not plain ASCII, names a `.md` file, is longer
than 300 characters, or is a JSON object carrying a string value: the gate's
and the smoke test's summaries are numbers, so a string in one means
something else got in. The step then prints which line numbers tripped it
and why, never the line, and exits 5. The output is still in the SSM
invocation, which is not public.

That is the second reading. The first is on the node: `http_eval` checks its
own summary with `private_keys_found` before printing it, and names cases by
index rather than by question.

## record_deploy.py

Reads the gate's and the smoke test's output files, picks out the numbers it
knows (`hit_rate`, `mrr`, `cases`, `errors`, `ungradable`, `checks`,
`passed`, `failed`, `ms_max`) and writes one item to the
`second-brain-ops-deploys` table, with the commit, the namespace and one of
`deployed`, `ungated`, `gate-failed`, `smoke-failed` or `rolled-back`. A key
it does not know cannot reach the table, so a script that starts printing
something new cannot put it there by accident. `python deploy/ops.py deploys`
reads the table back.

History lives there rather than in a file on `main`, because a bot that
committed a history file would put a commit on every deploy and then deploy
that commit.

## node_state.py

`nightly-cost.yml` runs this. It compares the running node with the
`OPS_STATE` repo variable and exits non-zero when they disagree, in either
direction: a node running while `OPS_STATE` says down is the expensive
mistake, and `OPS_STATE` left up with no node means `deploy.yml` is skipping
every run. It also reads the month-to-date bill, which costs a cent a call
and is what puts a real number in `docs/ops/cost.md`.

## The sh versus bash trap

`AWS-RunShellScript` runs its commands with `sh`, which on Ubuntu is dash. A
script that starts `set -euo pipefail` fails on its first line with "Illegal
option -o pipefail". `send_command.py` therefore invokes each script as
`bash /opt/sbt/deploy/pipeline/<script> <args>`, and the scripts use bash
features freely. Run them the same way by hand.

## deploy-namespace.sh NAMESPACE SHA VAULT_BUCKET

Checks `/opt/sbt` out at SHA, pins the overlay's `newTag` to SHA with `sed`,
applies the namespace, the `second-brain-ops-env` ConfigMap and the overlay,
then waits for the rollout and prints the pod, its image and whether it is
ready.

`VAULT_BUCKET` is `second-brain-vault-<account id>`. It carries the account
id, so it is passed in rather than committed.

**The empty-volume case.** A fresh node's volume has no index, and the API
stays unready until it has one, so the rollout below would wait 15 minutes
for a pod that cannot become ready. The script creates a one-off
`indexer-first` Job from the indexer CronJob and waits up to 45 minutes for
it. Staging's first build read 775 files, wrote 5,941 chunks and took 22
minutes.

It decides whether to do that from the Deployment's ready replica count,
read before the apply: readiness is `/api/ready?strict=1`, which answers 503
until the index holds at least one chunk, so a ready replica means a
populated volume. A normal deploy reads one field and skips. The check is
wrong in the cheap direction: an API that is unready for another reason runs
the indexer again, which is incremental and short on a populated volume.

Exit codes: 0 deployed, 2 a bad argument, 1 anything that failed.

## run-job.sh NAMESPACE SHA TEMPLATE JOBNAME

One script for both Jobs, because the gate and the smoke check differ only by
template. `TEMPLATE` is a path under `/opt/sbt`:

    deploy/k8s/gate-job.yaml     the eval gate, in staging
    deploy/k8s/smoke-job.yaml    the five fixed queries, in prod

It substitutes `${IMAGE}` with `envsubst`, rewrites the template's
`generateName` prefix to `JOBNAME-<first 12 of SHA>-` so the Job's name says
which deploy it belongs to, creates it, waits, prints the pod's logs and
deletes nothing. The logs are numbers only by construction: `http_eval`
checks its summary with `private_keys_found` before printing it.

A template that mounts the `eval-scorecard` ConfigMap gets it created first,
from `deploy/k8s/base/cloud-scorecard.json`, which is where `ops.py
record-cloud-scorecard` writes it, or from `deploy/eval/cloud-scorecard.json`,
which is where the older READMEs say it lives. Whichever the commit carries.

| exit | means |
|---|---|
| 0 | the container exited 0 |
| 1 | it exited 1: for the gate, eval drift (`EXIT_DRIFT`) |
| 2 | it exited 2: the summary was refused, `private_keys_found` matched (`EXIT_REFUSED`) |
| 3 | no scorecard is recorded yet, so the gate has nothing to compare against |
| 4 | anything else: a timeout, a failed init container, a pod with no exit code, a bad argument |

The code comes from the pod's `containerStatuses`, not from the Job's
condition, so the gate's own meaning survives the trip back to the workflow.
Exit 3 is not a failure of the deploy: the card can only be measured against a
cluster serving the synced vault, so the first deploy into a fresh
environment runs before one exists, and the caller decides what to do.

## rollback.sh NAMESPACE

`kubectl rollout undo` on the API Deployment, then waits for the rollout and
prints the image tag it landed on, for the issue the workflow opens. Exit
codes: 0 rolled back, 2 a bad argument, 1 anything that failed, including a
namespace with only one revision to go back to.

This is the one script that does not converge on a target. `rollout undo`
swaps the two newest revisions, so calling it twice restores the image it
just rolled away from. Call it once per failed deploy.

It also leaves `/opt/sbt`'s overlay pinned to the SHA that failed. That is
harmless, because the next `deploy-namespace.sh` checks the node out with
`--force` and pins the tag again before it applies anything.

## What the workflow passes

    python deploy/pipeline/send_command.py --sha "$SHA" --timeout 4200 \
      --script deploy/pipeline/deploy-namespace.sh -- staging "$SHA" "$VAULT_BUCKET"

    python deploy/pipeline/send_command.py --sha "$SHA" --timeout 2100 \
      --script deploy/pipeline/run-job.sh -- staging "$SHA" deploy/k8s/gate-job.yaml gate

    python deploy/pipeline/send_command.py --sha "$SHA" --timeout 4200 \
      --script deploy/pipeline/deploy-namespace.sh -- prod "$SHA" "$VAULT_BUCKET"

    python deploy/pipeline/send_command.py --sha "$SHA" --timeout 2100 \
      --script deploy/pipeline/run-job.sh -- prod "$SHA" deploy/k8s/smoke-job.yaml smoke

    python deploy/pipeline/send_command.py --sha "$SHA" --timeout 1200 \
      --script deploy/pipeline/rollback.sh -- prod

`--timeout` is the SSM execution timeout and has to be longer than the
script's own waits, or SSM kills the command while the script is still
waiting and the step's exit code says nothing useful. `deploy-namespace.sh`
waits up to 45 minutes for the first index and 15 for the rollout, so 4200
seconds; `run-job.sh` waits up to 30 minutes, so 2100.

## status.sh NAMESPACE

Read-only, and the first thing a runbook reaches for: the image each pod runs
and whether it is Ready, how the last Jobs ended, the CronJobs and their last
success, the PVC, and how full the node's root disk is. It changes nothing.

It does not print pod logs on purpose. The API's own logs can carry a query,
and a query is a question about someone's notes. The gate's and the smoke
test's logs are numbers by construction, and `run-job.sh` prints those itself.

## reindex.sh NAMESPACE

Runs the indexer once against a namespace that is already serving, and waits.
Until this existed there was no way to do that: `/api/index` is 403 under
`READ_ONLY=1`, `deploy-namespace.sh` creates its one-off Job only when the
Deployment has no ready replica, and the CronJob runs at 06:00 UTC. The
stale-index runbook needs it, and so does game-day scenario 3.

The Job comes from the CronJob (`kubectl create job --from=cronjob/...`), so
there is one pod template for the indexer and no copy to drift. It refuses to
start while another indexer Job is active: two writers on one volume is the
condition behind `docs/ops/postmortem-stale-index.md`. It prints the Job's
exit, never the indexer's log, which names the files it read.

## Running one by hand

Through the tunnel there is no shell on the node, so this goes the same way
the pipeline does:

    python deploy/pipeline/send_command.py --sha $SHA --timeout 1200 \
      --script deploy/pipeline/rollback.sh -- staging

On the node itself, with `kubectl` already on `KUBECONFIG`:

    bash /opt/sbt/deploy/pipeline/rollback.sh staging
