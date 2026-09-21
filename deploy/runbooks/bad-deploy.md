# The gate blocked a promotion, or a bad image is in prod

Game-day scenario 4. Two different mornings, one runbook: either the pipeline
stopped a build before prod saw it, or something reached prod that should not
have. Read `README.md` in this folder first if you do not know how to reach
the node.

## What you will see

**The gate blocked it.** An issue titled `Deploy failed: <first 7 of the
SHA>`, label `deploy-failure`, opened by `.github/workflows/deploy.yml`. It
carries a table of the staging and prod job results, a link to the run, and a
line saying both namespaces roll back on failure. In the run, the failing step
is "Score it against the recorded card", and `send_command.py` prints the
node's output followed by its status and exit code. `run-job.sh`'s codes:

    exit 1   eval drift: the gate's own verdict
    exit 2   the summary was refused, private_keys_found matched
    exit 3   no recorded scorecard yet, which is not a failure
    exit 4   a timeout, a failed init container, a bad argument

A step that exits 5 is different: that is `send_command.py` itself refusing to
print what came back (`deploy/pipeline/README.md`).

**A bad image is in prod.** An issue titled `Alert: CanaryHitRateDropped in
prod`, or `Alert: CanaryErrors in prod` if it cannot reach the API at all.
In Grafana, "Canary hit rate" is below its baseline line, and "Search latency"
and "5xx share" say whether it is a quality problem or an outage.

## What it means

The gate runs as a Job inside the cluster, scores staging over `/api/search`,
and compares the result with the recorded card using `drift_verdict`, which
flags a hit-rate drop of 5 points or more. The prod job needs the staging job,
so a gate failure means prod never got the image, and the staging job's
`Roll staging back` step already ran. The deploy is recorded either way, with
an outcome of `gate-failed`, `rolled-back`, `smoke-failed`, `ungated` or
`deployed` (`.github/workflows/deploy.yml`,
`deploy/pipeline/record_deploy.py`).

One thing to know before trusting the gate: `cloud-scorecard.json` is not in
git yet (`deploy/eval/README.md`). Until it is recorded, `run-job.sh` exits 3,
the workflow deploys anyway, and the record says `ungated`. In that state the
canary is the only quality signal there is.

What is not broken: the deploy history is in DynamoDB and survives
`ops.py down`; the eval set and the vault copy never left the cluster, and
what reached the public log is numbers only, checked twice — once by
`http_eval` on the node and once by `output_guard.py` before printing.

## Check

1. Read the run linked from the issue. Which step, which exit code. An exit 5
   printed nothing in public on purpose; the output is in the SSM invocation,
   which is not public.

2. What was recorded:

        python deploy/ops.py deploys

   Columns are `sha`, `deployed_at`, `namespace`, `outcome`, `hit_rate`,
   `ms_max`. Compare `hit_rate` with the card the gate scored against.

3. The dashboard, for prod's current state:

        python deploy/ops.py tunnel --to grafana     # then http://localhost:3000

   "Canary hit rate" against its baseline, "5xx share", "Search latency". A
   quality drop with healthy latency and no 5xx is retrieval, not an outage.

4. Ask prod what it answers, in a second window:

        python deploy/ops.py tunnel --to prod --local-port 8001
        curl.exe "http://localhost:8001/api/ready?strict=1"

   The image tag prod is running is printed by the two scripts that change
   something (`deploy-namespace.sh` and `rollback.sh`), so the read-only
   answer to "what is deployed" is the history in step 2.

## Fix

**If the gate blocked it, first decide whether the drop is a bug or the
point.** Nothing needs undoing: prod never got the image and staging already
rolled back.

A change meant to move retrieval re-records the card, with a tunnel open in
another window:

    python deploy/ops.py record-cloud-scorecard --dataset <private eval set> --vault-dir <staging mirror>

It writes `deploy/k8s/base/cloud-scorecard.json`, which holds a date, the
dataset's case count and hash, and hit rate, MRR and case counts. Commit it
and deploy again. A change that was not meant to move retrieval is a bug in
the commit; fix that instead.

**If a bad image is in prod, roll it back once.**

    python deploy/pipeline/send_command.py --sha <40-hex commit> --timeout 1200 \
      --script deploy/pipeline/rollback.sh -- prod

`--sha` here is only the commit the node checks out to get the script, so use
one whose `deploy/pipeline/` you trust, normally the tip of main. The script
prints `rolling back from <tag>` and `rolled back to <tag>`. Call it once per
failed deploy: `rollout undo` swaps the two newest revisions, so a second call
restores the image you just left. A namespace with only one revision has
nothing to go back to and the script exits 1.

**If the previous image is also bad, deploy a known-good commit.** CI must
have published its image. Either run `deploy.yml` by hand — it takes a `sha`
input — or send the namespace there directly:

    python deploy/pipeline/send_command.py --sha <good 40-hex commit> --timeout 4200 \
      --script deploy/pipeline/deploy-namespace.sh -- prod <good 40-hex commit> second-brain-vault-ACCOUNT_ID

## Verify

Run the smoke check against prod by hand. It is seven checks — a readiness
call, five fixed generic queries against `/api/search`, and one write that
must return 403 — printed as pass or fail with numbers
(`backend/eval/smoke.py`):

    python deploy/pipeline/send_command.py --sha <40-hex commit> --timeout 2100 \
      --script deploy/pipeline/run-job.sh -- prod <40-hex commit> deploy/k8s/smoke-job.yaml smoke

Exit 0 means the Job's container exited 0. Then "Canary hit rate" returns to
its baseline within a couple of runs, one every 15 minutes, and the bridge
closes the alert issue. `python deploy/ops.py deploys` should show the row you expect on top.
Close the deploy-failure issue yourself: nothing closes that one for you.

## If it keeps happening

- The drift rule is `drift_verdict` in `backend/eval/scorecard.py`, and 5
  points is the number it flags at. The card it compares against is
  `deploy/k8s/base/cloud-scorecard.json`, or `deploy/eval/cloud-scorecard.json`
  in older commits; `run-job.sh` reads whichever the commit carries.
- Deploys landing `ungated` mean there is still no card. Record one
  (`deploy/eval/README.md`).
- The canary's baseline and its ten questions:
  `deploy/k8s/base/canary-card.json`, `deploy/k8s/base/cronjob-canary.yaml`
  and `backend/eval/canary.py`. If a real retrieval change moved the numbers,
  the baseline card is stale too, not just the gate's.
- What the pipeline may print, and why a step printed nothing:
  `deploy/pipeline/output_guard.py`.
