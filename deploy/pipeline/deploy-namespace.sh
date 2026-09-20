#!/usr/bin/env bash
# Put one namespace on one commit: check the node out at that SHA, pin the
# overlay's image tag to it, apply, and wait until the API serves it.
#
#   bash deploy/pipeline/deploy-namespace.sh NAMESPACE SHA VAULT_BUCKET
#
# The pipeline never reaches the cluster directly, so this runs on the node
# through SSM Run Command. AWS-RunShellScript runs its commands with sh,
# which on Ubuntu is dash, and dash stops on `set -o pipefail`. That is why
# send_command.py invokes this as `bash <script>` and why everything below
# may use bash.
#
# It prints counts, status words, image tags and SHAs. It never reads a note,
# a note path or an eval question: this repository is public and the vault
# is not.
set -euo pipefail

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

REPO="https://github.com/Bryancruzcb/second-brain-tools"
CHECKOUT=/opt/sbt
DEPLOYMENT=second-brain
INDEXER_CRONJOB=second-brain-indexer
# The one-off job that fills an empty volume. A fixed name, because it is the
# marker the next run reads, and because two of them would fight over the
# same volume.
FIRST_JOB=indexer-first
# 45 minutes. Staging's first build of the 775-file vault read every file,
# wrote 5,941 chunks and took 22 minutes on about one of the node's two
# vCPUs, so this is double the measured run.
INDEX_TIMEOUT_S=2700
INDEX_POLL_S=60
# The API is unready while its models load, which the readiness probe allows
# ten minutes for.
ROLLOUT_TIMEOUT=15m

if [ "$#" -ne 3 ]; then
  echo "usage: bash deploy-namespace.sh NAMESPACE SHA VAULT_BUCKET" >&2
  exit 2
fi
NAMESPACE=$1
SHA=$2
VAULT_BUCKET=$3

# The image tag is the full commit SHA that CI published. A branch name or a
# short SHA here names a tag that does not exist in GHCR, and the pod would
# sit in ImagePullBackOff until the rollout timed out 15 minutes later.
if ! printf '%s' "$SHA" | grep -Eq '^[0-9a-f]{40}$'; then
  echo "SHA is not 40 hex characters: $SHA" >&2
  exit 2
fi

# cloud-init installs k3s and nothing else, and git is not in the Ubuntu
# image. The pipeline's sender clones before it calls this, so the install
# below only matters when someone runs the script by hand on a fresh node.
# It belongs in cloud-init.yaml, which is another file's job.
if ! command -v git >/dev/null 2>&1; then
  echo "installing git"
  DEBIAN_FRONTEND=noninteractive apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git
fi

echo "namespace $NAMESPACE sha $SHA"

# --- the checkout -----------------------------------------------------------
# --force discards the sed below from the last deploy, so the overlay starts
# from what is in git every time.
if [ ! -d "$CHECKOUT/.git" ]; then
  echo "cloning $CHECKOUT"
  git clone --quiet "$REPO" "$CHECKOUT"
fi
git -C "$CHECKOUT" fetch --quiet origin
git -C "$CHECKOUT" checkout --quiet --detach --force "$SHA"
echo "checkout $(git -C "$CHECKOUT" rev-parse HEAD)"

OVERLAY="$CHECKOUT/deploy/k8s/overlays/$NAMESPACE"
if [ ! -d "$OVERLAY" ]; then
  echo "no overlay at deploy/k8s/overlays/$NAMESPACE" >&2
  exit 2
fi

# --- pin the tag ------------------------------------------------------------
# sed rather than `kustomize edit set image`, because the node has kubectl and
# its built-in kustomize, not the standalone binary (deploy/k8s/README.md).
# The base names :unset, a tag that does not exist, so an apply that skipped
# this step fails on the pull instead of running whatever ran last.
sed -i "s|newTag: .*|newTag: $SHA|" "$OVERLAY/kustomization.yaml"
if ! grep -q "newTag: $SHA" "$OVERLAY/kustomization.yaml"; then
  echo "failed to pin newTag in $OVERLAY/kustomization.yaml" >&2
  exit 1
fi
echo "pinned newTag $SHA"

# --- is the volume already indexed? -----------------------------------------
# Read this before the apply. The apply starts a rollout, and the new pod is
# not ready yet whatever the volume holds.
#
# The test is the Deployment's ready replica count. Readiness is
# /api/ready?strict=1, which answers 503 until the Chroma collection holds at
# least one chunk, so a Deployment with a ready replica is a Deployment whose
# index has chunks. It costs one call and needs nothing mounted.
#
# It is wrong in the cheap direction. An API that is unready for some other
# reason makes this run the indexer again, and a run against a populated
# volume is incremental and takes minutes. Guessing the other way would leave
# the rollout waiting 15 minutes for a pod that can never become ready.
READY_REPLICAS=$(kubectl -n "$NAMESPACE" get deployment "$DEPLOYMENT" \
  -o jsonpath='{.status.readyReplicas}' 2>/dev/null || true)
READY_REPLICAS=${READY_REPLICAS:-0}
echo "ready replicas before apply $READY_REPLICAS"

# --- apply ------------------------------------------------------------------
kubectl apply -f "$OVERLAY/namespace.yaml"

# The vault bucket's name carries the AWS account id, so it is created per
# namespace instead of committed. create | apply rather than create alone, so
# a second deploy updates it instead of failing on AlreadyExists.
kubectl create configmap second-brain-ops-env -n "$NAMESPACE" \
  --from-literal=VAULT_BUCKET="$VAULT_BUCKET" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -k "$OVERLAY"

# --- first index ------------------------------------------------------------
wait_for_first_index() {
  local started elapsed succeeded failed state
  started=$(date +%s)
  while :; do
    # One call for both counters: a poll that costs two calls for 45 minutes
    # is 90 calls for nothing.
    state=$(kubectl -n "$NAMESPACE" get job "$FIRST_JOB" \
      -o jsonpath='{.status.succeeded} {.status.failed}' 2>/dev/null || true)
    succeeded=${state%% *}
    failed=${state##* }
    succeeded=${succeeded:-0}
    failed=${failed:-0}
    elapsed=$(( $(date +%s) - started ))
    if [ "$succeeded" -ge 1 ]; then
      echo "$FIRST_JOB succeeded after ${elapsed}s"
      return 0
    fi
    if [ "$failed" -ge 1 ]; then
      echo "$FIRST_JOB failed after ${elapsed}s" >&2
      return 1
    fi
    if [ "$elapsed" -ge "$INDEX_TIMEOUT_S" ]; then
      echo "$FIRST_JOB unfinished after ${elapsed}s, limit ${INDEX_TIMEOUT_S}s" >&2
      return 1
    fi
    echo "$FIRST_JOB running ${elapsed}s"
    sleep "$INDEX_POLL_S"
  done
}

if [ "$READY_REPLICAS" -ge 1 ]; then
  echo "index present, skipping $FIRST_JOB"
else
  # A previous run's job may still be here. A finished one is either the
  # success this needs or a failure worth repeating, and the CronJob's
  # template sets backoffLimit 0, so a failed job never retries itself.
  PRIOR_FAILED=$(kubectl -n "$NAMESPACE" get job "$FIRST_JOB" \
    -o jsonpath='{.status.failed}' 2>/dev/null || true)
  if [ "${PRIOR_FAILED:-0}" -ge 1 ]; then
    echo "deleting failed $FIRST_JOB"
    kubectl -n "$NAMESPACE" delete job "$FIRST_JOB" --wait=true
  fi
  if kubectl -n "$NAMESPACE" get job "$FIRST_JOB" >/dev/null 2>&1; then
    echo "$FIRST_JOB exists, waiting on it"
  else
    kubectl -n "$NAMESPACE" create job --from="cronjob/$INDEXER_CRONJOB" "$FIRST_JOB"
  fi
  wait_for_first_index
fi

# --- rollout ----------------------------------------------------------------
kubectl -n "$NAMESPACE" rollout status "deployment/$DEPLOYMENT" --timeout="$ROLLOUT_TIMEOUT"

kubectl -n "$NAMESPACE" get pods \
  -l app.kubernetes.io/name=second-brain,app.kubernetes.io/component=api \
  -o custom-columns=POD:.metadata.name,IMAGE:.spec.containers[0].image,READY:.status.containerStatuses[0].ready
