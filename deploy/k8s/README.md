# Kubernetes manifests

Single-node k3s, two namespaces on one machine. `staging` takes every deploy
first and gets scored by the eval gate; `prod` gets the same image only if
that score holds. Neither is reachable from the internet: the node has no
inbound rules and there is no Ingress, so the way in is an SSM port forward
(`python deploy/ops.py tunnel`).

    base/            deployment, service, PVC, config, network policies, indexer and canary CronJobs
    overlays/staging one API replica on the base's resource requests
    overlays/prod    the same, with the memory and CPU it actually needs held for it
    gate-job.yaml    created per deploy by the pipeline, not part of any overlay

## Apply

    kubectl apply -k deploy/k8s/overlays/staging
    kubectl apply -k deploy/k8s/overlays/prod

Both fail on the image pull until the tag is set, which is deliberate: the
base names `:unset`, a tag that does not exist in GHCR, so an apply that
forgot to pin a commit stops instead of running whatever ran last. The
pipeline pins it with the merged SHA:

    sed -i "s|newTag: .*|newTag: $SHA|" deploy/k8s/overlays/staging/kustomization.yaml
    kubectl apply -k deploy/k8s/overlays/staging

(`sed` rather than `kustomize edit set image`, because the node has kubectl
and its built-in kustomize, not the standalone binary.)

Each overlay also pins its Service's cluster address (`service-ip.yaml`), so
the tunnel below has a fixed target. `clusterIP` can't change on a live
Service: in a namespace whose Service was created before the pin, run
`kubectl -n <namespace> delete service second-brain` once before the apply.

## First deploy on a fresh node

`python deploy/ops.py up` gives a node running k3s and nothing else. The
volume lives on the node's root disk, so every `ops.py down` takes the index
with it and the next `up` starts empty. On a fresh node, after pinning the
tag as above:

    kubectl apply -f deploy/k8s/overlays/staging/namespace.yaml
    kubectl create configmap second-brain-ops-env -n staging \
      --from-literal=VAULT_BUCKET=second-brain-vault-ACCOUNT_ID
    kubectl apply -k deploy/k8s/overlays/staging
    kubectl -n staging create job --from=cronjob/second-brain-indexer indexer-first

The API starts before the index exists and should answer 503 on
`/api/ready?strict=1` until the job's first chunks are in the store: while the
index looks empty, the probe reopens the store once it sees the write stamp
move. It can't rely on the job's refresh call at the end of the run, because a
pod that isn't Ready has no Service endpoints for that call to reach. Staging's
first run on 2026-09-18 used an image from before this probe, so the next
fresh node is the first to exercise it. That run's first build read 775 files,
wrote 5,941 chunks, and took 22 minutes, with `kubectl top` showing the
indexer at about one CPU.

## Reaching the API

    python deploy/ops.py tunnel               # staging on localhost:8000
    python deploy/ops.py tunnel --env prod --local-port 8001

The session's far end is the SSM agent on the node, which connects on to the
pinned service address. Nothing listens on the node's own port 8000, because
the Service is ClusterIP only, so the plain `AWS-StartPortForwardingSession`
document reaches nothing.

## Running commands on the node

SSM Run Command's `AWS-RunShellScript` runs its commands with `sh`, which on
Ubuntu is dash: a script that starts `set -euo pipefail` fails on its first
line with "Illegal option -o pipefail". Write the script to a file on the node
and run that with bash. The week 4 pipeline will drive the cluster the same way.

## Two ConfigMaps that are not in git

**`second-brain-ops-env`** holds the vault bucket's name, which contains the
AWS account id. This repository is public, so it is created per namespace
instead of committed:

    kubectl create configmap second-brain-ops-env -n staging \
      --from-literal=VAULT_BUCKET=second-brain-vault-ACCOUNT_ID

**`eval-scorecard`** is the numbers-only card the gate compares each deploy
against. It is committed (`deploy/eval/cloud-scorecard.json`) but has to
reach the cluster as a ConfigMap:

    kubectl create configmap eval-scorecard -n staging \
      --from-file=cloud-scorecard.json=deploy/eval/cloud-scorecard.json \
      --dry-run=client -o yaml | kubectl apply -f -

## The gate

    IMAGE=ghcr.io/bryancruzcb/second-brain-backend:$SHA \
      envsubst < deploy/k8s/gate-job.yaml | kubectl create -n staging -f -

It runs in the cluster, not on a GitHub runner, because it reads the private
dataset from S3 and the private vault from the volume. It prints numbers
only and refuses to print anything that fails `private_keys_found`, so the
workflow log stays clean. `backoffLimit: 0`: a gate that retries is a gate
that eventually passes.

## What is deliberately not here

- **No Ingress and no Service of type LoadBalancer.** The design's whole
  privacy argument rests on nothing from the internet reaching the node.
- **No Secret objects.** The one long-lived credential in this project is
  the sync uploader's key, and it never leaves the desktop. The node reads
  S3 with its instance role and Grafana's password comes from SSM.
- **No HorizontalPodAutoscaler.** One node, one replica per namespace. The
  interesting failures here are a stale index and a full disk, not load.

## Measured resources

Read from each container's cgroup (`memory.peak`) on staging, on the
m7i-flex.large with the 775-file vault:

| | 2026-09-18, image `b202502` | 2026-09-19, image `4eb0949` |
|---|---|---|
| API, models loaded, empty index | 469 MiB | 469 MiB |
| API, 5,941-chunk index open | 804 MiB | 799 MiB |
| API under queries | OOMKilled at the 2 GiB limit on its second query | 999 MiB peak over 63 queries, four at a time among them |
| Indexer, first build | 1,228 MiB, 22 minutes | 1,222 MiB, 22 minutes |

The difference between the two API rows under queries is the reranker's
batch: the first image scored the whole 30-deep pool in one ONNX pass, the
second scores one pair per pass (`RERANK_BATCH_SIZE`, see
`backend/config.py`). The requests and limits in `base/` and
`overlays/prod/` come from the second column.

On the whole node that asks for 900 MiB (staging API) plus 1 GiB (prod
API) plus 1,280 MiB for each indexer, about 4.4 GiB at 06:00 UTC when both
CronJobs run, out of 7.6 GiB, with monitoring still to come in week 3.

Search latency through the tunnel on 2026-09-19, the same 63 queries: p50
1.53 s and p95 1.92 s one at a time, and p50 6.6 s four at a time, because
one API worker serves them in turn.

## Known follow-ups

- **The p95 alert in PLAN.md section 6.5 is set at 1.5 seconds**, below the
  1.92 s staging measured through the tunnel. Week 3 sets it from the
  in-cluster request histogram instead, or it fires on ordinary traffic.
- **Both namespaces' indexers start at 06:00 UTC** and each runs on about
  one of the node's two CPUs. The nightly run is incremental and short, but
  if it grows, prod's schedule should move later.
- **The API container runs as root**, because the image has no non-root user
  and the volume is created root-owned. Adding a user to the Dockerfile and
  an `fsGroup` here is a small change that wants a live node to verify, so
  it waits for one. Privilege escalation is already off and every capability
  is dropped.
