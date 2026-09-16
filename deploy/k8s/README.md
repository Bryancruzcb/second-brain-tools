# Kubernetes manifests

Single-node k3s, two namespaces on one machine. `staging` takes every deploy
first and gets scored by the eval gate; `prod` gets the same image only if
that score holds. Neither is reachable from the internet: the node has no
inbound rules and there is no Ingress, so the way in is an SSM port forward
(`python deploy/ops.py tunnel`).

    base/            deployment, service, PVC, config, network policies, indexer CronJob
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

## Known follow-ups

- **Resource requests and limits are provisional.** The node has never run.
  Week 2 ends by measuring real usage under a query and a reindex, and
  setting them from that; until then they are informed guesses that fit two
  namespaces plus monitoring into 8 GB.
- **The API container runs as root**, because the image has no non-root user
  and the volume is created root-owned. Adding a user to the Dockerfile and
  an `fsGroup` here is a small change that wants a live node to verify, so
  it waits for one. Privilege escalation is already off and every capability
  is dropped.
