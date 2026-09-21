# The API pod is gone or will not become Ready

Game-day scenario 1. Read `README.md` in this folder first if you do not know
how to reach the node.

## What you will see

An issue titled `Alert: ApiNotReady in prod` (or `in staging`), label `alert`,
severity critical. The rule fires when the Deployment has fewer available
replicas than it asks for, for 5 minutes
(`deploy/monitoring/rules/second-brain.yml`).

Often a second issue follows: `Alert: CanaryErrors in <namespace>`, which is
the canary failing to reach the API on two runs in a row. It runs every 15
minutes (`deploy/k8s/base/cronjob-canary.yaml`).

In Grafana, on the "Second Brain API" dashboard with `$namespace` set to the
one in the alert: "API replicas available" sits at 0, "Requests per second by
status" goes flat, and "Canary hit rate" stops reporting. "Pod memory" is
worth a look on the way past: it draws each container against its limit.

## What it means

Each namespace runs one API replica, and readiness is `/api/ready?strict=1`,
which answers 503 until the embedding model, the Chroma collection, the
lexical index and the reranker have all loaded and the collection holds at
least one chunk (`deploy/k8s/base/deployment.yaml`). So this alert covers both
a pod that died and a pod that is running but cannot serve properly. A normal
rollout does not trip it: `maxUnavailable: 0` keeps the old pod serving until
the new one is Ready.

What is not broken: the index and the vault copy are on the namespace's
volume, which outlives the pod; the vault itself is on the desktop and in S3;
and the other namespace has its own Deployment, Service and volume, so prod
being down says nothing about staging.

## Check

1. Did something just deploy?

        python deploy/ops.py deploys

   This reads DynamoDB and needs no node. The `outcome` column says
   `deployed`, `ungated`, `gate-failed`, `smoke-failed` or `rolled-back`.

2. Look at the dashboard.

        python deploy/ops.py tunnel --to grafana     # then http://localhost:3000

   "API replicas available", then "Pod memory" against the limit line, then
   "Root disk used". A pod killed for memory and a pod that cannot write
   anywhere look the same from outside.

3. Ask the node what the pods are doing:

        python deploy/pipeline/send_command.py --sha <40-hex commit> --timeout 300           --script deploy/pipeline/status.sh -- prod

   Read-only. `RESTARTS` climbing is a crash loop; `PHASE` stuck at `Pending`
   is a pod nothing will schedule; a container exit code of 137 is the kernel
   killing it for memory, which the "Pod memory" panel then confirms.

4. Ask the API itself, in a second window:

        python deploy/ops.py tunnel --to prod --local-port 8001
        curl.exe "http://localhost:8001/api/ready?strict=1"

   A 200 with `"index_populated": true` means it is serving. A 503 body names
   which component is still false. A tunnel that connects but reaches nothing
   means the pod has no Service endpoints, which is itself the answer.

## Fix

**First, wait.** Kubernetes restarts a pod that fails liveness on
`/api/health` without being asked, and the readiness probe allows ten minutes
for models to load on a cold start (`failureThreshold: 40` at
`periodSeconds: 15`, `deploy/k8s/base/deployment.yaml`). If the alert is
younger than that and the pod is loading, there is nothing to do.

**Then, re-apply the namespace.** This converges: it checks the node out at
the commit, pins the image tag, applies the overlay, waits for the rollout and
prints the pod, its image and whether it is ready.

    python deploy/pipeline/send_command.py --sha <40-hex commit> --timeout 4200 \
      --script deploy/pipeline/deploy-namespace.sh -- prod <40-hex commit> second-brain-vault-ACCOUNT_ID

Use the SHA the namespace is supposed to be on, from `ops.py deploys`. This is
not a free action: if the Deployment has no ready replica, the script decides
the volume is empty and runs a one-off `indexer-first` Job first, waiting up to
45 minutes for it. Staging's first build read 775 files, wrote 5,941 chunks and
took 22 minutes (`deploy/k8s/README.md`).

**If the pod is failing on a new image, roll back instead.**

    python deploy/pipeline/send_command.py --sha <40-hex commit> --timeout 1200 \
      --script deploy/pipeline/rollback.sh -- prod

Call it once per failed deploy. `rollout undo` swaps the two newest revisions,
so a second call puts back the image you just rolled away from. A namespace
with only one revision has nothing to go back to and the script exits 1.
See `bad-deploy.md`.

**Last, replace the node.** `python deploy/ops.py down` then `python
deploy/ops.py up`. This one destroys data: the volume lives on the node's
root disk, so `down` takes the index and the model cache with it, and the
next deploy rebuilds the index, 22 minutes for 5,941 chunks on staging's first
build. The vault copy comes back from S3, and Terraform state and the deploy
history are not on the node. Set `OPS_STATE` to match afterwards; `ops.py`
prints the command.

## Verify

"API replicas available" is back at 1 and "Requests per second by status" is
moving again. `curl.exe "http://localhost:8001/api/ready?strict=1"` answers
200 with `"index_populated": true`. "Canary hit rate" is back at its baseline
line within a couple of runs; the canary runs every 15 minutes
(`deploy/k8s/base/canary-card.json`). The bridge comments on the issue and
closes it when the alert resolves; the closed issue is the signal it is over.

## If it keeps happening

- Killed for memory: the requests and limits are in
  `deploy/k8s/base/deployment.yaml` and, for prod,
  `deploy/k8s/overlays/prod/resources.yaml`. What was actually measured is in
  `deploy/k8s/README.md`, "Measured resources" — change them against that
  table, not against a guess.
- Unready for longer than the probe allows: the readiness probe's
  `failureThreshold` and `periodSeconds` in `deploy/k8s/base/deployment.yaml`.
- Unready only on a fresh node: that is the first-index path, described in
  `deploy/pipeline/README.md` under "The empty-volume case".
- Alerting too early or too late: `ApiNotReady`'s `for:` in
  `deploy/monitoring/rules/second-brain.yml`, with the reason for the current
  value in `deploy/monitoring/README.md`.
