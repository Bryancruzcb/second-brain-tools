#!/usr/bin/env bash
# Run one Job from a template in the checkout, wait for it, print its logs,
# and exit with a code that says what happened.
#
#   bash deploy/pipeline/run-job.sh NAMESPACE SHA TEMPLATE JOBNAME
#
# The gate and the smoke check are the same operation: create a Job from the
# image being deployed, wait, and report. They differ only by TEMPLATE, which
# is a path under the checkout, so one script covers both and the caller
# decides what a non-zero code means.
#
# exit 0  the Job's container exited 0
# exit 1  it exited 1, which for the gate is eval drift (EXIT_DRIFT)
# exit 2  it exited 2, which for the gate is a summary it refused to print
#         because private_keys_found matched (EXIT_REFUSED)
# exit 3  the gate has no recorded scorecard yet, so there is nothing to
#         compare against and the caller decides whether that stops the run
# exit 4  anything else: a timeout, an init container that failed, a pod that
#         never reported an exit code, a bad argument
#
# The codes below 3 are the container's own, read from the pod status rather
# than guessed from the Job's condition, so the gate's meaning survives the
# trip back through SSM to the workflow.
#
# The logs this prints are numbers only by construction: http_eval checks its
# summary with private_keys_found before printing it, and names cases by
# index. This repository is public and the vault is not.
set -euo pipefail

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

CHECKOUT=/opt/sbt
IMAGE_REPO=ghcr.io/bryancruzcb/second-brain-backend
SCORECARD_CONFIGMAP=eval-scorecard
SCORECARD_KEY=cloud-scorecard.json
# The gate scores the whole eval set over HTTP against one API worker, which
# serves queries in turn. 30 minutes is well past any run measured so far and
# still short enough that a stuck Job fails inside one SSM command.
JOB_TIMEOUT_S=1800
JOB_POLL_S=15

EXIT_NO_CARD=3
EXIT_OTHER=4

if [ "$#" -ne 4 ]; then
  echo "usage: bash run-job.sh NAMESPACE SHA TEMPLATE JOBNAME" >&2
  exit "$EXIT_OTHER"
fi
NAMESPACE=$1
SHA=$2
TEMPLATE=$3
JOBNAME=$4

if ! printf '%s' "$SHA" | grep -Eq '^[0-9a-f]{40}$'; then
  echo "SHA is not 40 hex characters: $SHA" >&2
  exit "$EXIT_OTHER"
fi

case "$TEMPLATE" in
  /*) TEMPLATE_PATH=$TEMPLATE ;;
  *) TEMPLATE_PATH="$CHECKOUT/$TEMPLATE" ;;
esac
if [ ! -f "$TEMPLATE_PATH" ]; then
  echo "no template at $TEMPLATE_PATH" >&2
  exit "$EXIT_OTHER"
fi

# envsubst comes from gettext-base, which cloud-init does not install and the
# Ubuntu image does not reliably carry. Installing it only when it is missing
# keeps every later deploy off the network. It belongs in cloud-init.yaml,
# which is another file's job.
if ! command -v envsubst >/dev/null 2>&1; then
  echo "installing gettext-base"
  DEBIAN_FRONTEND=noninteractive apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq gettext-base
fi

export IMAGE="$IMAGE_REPO:$SHA"
echo "namespace $NAMESPACE job $JOBNAME sha $SHA"

# --- the scorecard the gate compares against --------------------------------
# Keyed off what the template mounts rather than off its file name, because
# the ConfigMap is a requirement of the gate's pod, not of a path.
if grep -q "name: $SCORECARD_CONFIGMAP" "$TEMPLATE_PATH"; then
  # Two paths because the repository holds two answers. `ops.py
  # record-cloud-scorecard` writes deploy/k8s/base/, next to the canary's
  # card and the manifests; deploy/eval/README.md, deploy/k8s/README.md and
  # http_eval's --record example still say deploy/eval/. Reading both means a
  # card recorded either way is found, and a commit that moves it does not
  # take the gate down with it.
  CARD=""
  for candidate in "$CHECKOUT/deploy/k8s/base/$SCORECARD_KEY" "$CHECKOUT/deploy/eval/$SCORECARD_KEY"; do
    if [ -f "$candidate" ]; then
      CARD=$candidate
      break
    fi
  done
  if [ -z "$CARD" ]; then
    # Not a failure of this script. The card can only be measured against a
    # cluster serving the synced vault, so the first deploy into a fresh
    # environment runs before one exists.
    echo "no recorded scorecard, nothing to compare against"
    exit "$EXIT_NO_CARD"
  fi
  kubectl create configmap "$SCORECARD_CONFIGMAP" -n "$NAMESPACE" \
    --from-file="$SCORECARD_KEY=$CARD" \
    --dry-run=client -o yaml | kubectl apply -f -
fi

# --- create the Job ---------------------------------------------------------
# The template carries generateName, not name, because a Job's pod template is
# immutable once created and every run needs its own. Rewriting the prefix
# keeps the server's uniqueness suffix while putting JOBNAME and the commit in
# the name, so `kubectl get jobs` says which deploy a Job belongs to.
if ! grep -q '^[[:space:]]*generateName:' "$TEMPLATE_PATH"; then
  echo "$TEMPLATE_PATH has no generateName, so its Job cannot be unique per run" >&2
  exit "$EXIT_OTHER"
fi
PREFIX="$JOBNAME-${SHA:0:12}-"

CREATED=$(envsubst < "$TEMPLATE_PATH" \
  | sed "s|^\([[:space:]]*\)generateName:.*|\1generateName: $PREFIX|" \
  | kubectl create -n "$NAMESPACE" -f - -o name)
JOB=${CREATED#*/}
echo "created $JOB"

# --- wait -------------------------------------------------------------------
# Polling rather than `kubectl wait`, which takes one condition at a time and
# so cannot watch for complete and failed together without two backgrounded
# waits. The exit code comes from the pod afterwards either way.
started=$(date +%s)
while :; do
  state=$(kubectl -n "$NAMESPACE" get job "$JOB" \
    -o jsonpath='{.status.succeeded} {.status.failed}' 2>/dev/null || true)
  succeeded=${state%% *}
  failed=${state##* }
  succeeded=${succeeded:-0}
  failed=${failed:-0}
  elapsed=$(( $(date +%s) - started ))
  if [ "$succeeded" -ge 1 ] || [ "$failed" -ge 1 ]; then
    echo "$JOB finished after ${elapsed}s, succeeded=$succeeded failed=$failed"
    break
  fi
  if [ "$elapsed" -ge "$JOB_TIMEOUT_S" ]; then
    echo "$JOB unfinished after ${elapsed}s, limit ${JOB_TIMEOUT_S}s" >&2
    exit "$EXIT_OTHER"
  fi
  sleep "$JOB_POLL_S"
done

# --- logs and the container's exit code -------------------------------------
# backoffLimit is 0 on both templates, so there is one pod. Take the newest
# anyway, so a template that later allows a retry still reports the last try.
POD=$(kubectl -n "$NAMESPACE" get pods \
  -l "batch.kubernetes.io/job-name=$JOB" \
  --sort-by=.metadata.creationTimestamp -o name 2>/dev/null | tail -n 1 || true)
POD=${POD#*/}
if [ -z "$POD" ]; then
  echo "$JOB left no pod to read" >&2
  exit "$EXIT_OTHER"
fi

kubectl -n "$NAMESPACE" logs "$POD" --tail=-1 || true

# containerStatuses holds the app containers only, so an init container that
# failed leaves this empty and lands in exit 4 rather than being read as a
# pass. The highest code wins, so a second container could not hide a failure.
CODE=""
for value in $(kubectl -n "$NAMESPACE" get pod "$POD" \
  -o jsonpath='{range .status.containerStatuses[*]}{.state.terminated.exitCode}{" "}{end}' 2>/dev/null || true); do
  if [ -z "$CODE" ] || [ "$value" -gt "$CODE" ]; then
    CODE=$value
  fi
done

if [ -z "$CODE" ]; then
  echo "$JOB reported no container exit code"
  kubectl -n "$NAMESPACE" get pod "$POD" \
    -o custom-columns=POD:.metadata.name,PHASE:.status.phase,REASON:.status.reason
  exit "$EXIT_OTHER"
fi

echo "$JOB container exit $CODE"
case "$CODE" in
  0|1|2) exit "$CODE" ;;
  *) exit "$EXIT_OTHER" ;;
esac
