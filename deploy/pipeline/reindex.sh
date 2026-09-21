#!/usr/bin/env bash
# Run the indexer once, now, against a namespace that is already serving.
#
#   bash deploy/pipeline/reindex.sh NAMESPACE
#
# Until this existed there was no way to reindex a healthy namespace: the
# API's /api/index is 403 under READ_ONLY=1, deploy-namespace.sh creates its
# one-off Job only when the Deployment has no ready replica, and the CronJob
# runs at 06:00 UTC. The stale-index runbook needs it, and so does game-day
# scenario 3.
#
# The Job is created from the CronJob rather than from a manifest of its own,
# so there is one pod template for the indexer and no copy to drift.
#
# It prints counts and status words. The indexer's own output names files it
# read, so this prints its exit code and never its log: read the log on the
# node with kubectl if it failed, where it is not public.
set -euo pipefail

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

CRONJOB=second-brain-indexer
# 45 minutes. A first build of the 775-file vault took 22 minutes on this
# node; an incremental run over a populated volume is minutes.
TIMEOUT_S=2700
POLL_S=30

if [ "$#" -ne 1 ]; then
  echo "usage: bash reindex.sh NAMESPACE" >&2
  exit 2
fi
NAMESPACE=$1

# concurrencyPolicy: Forbid stops the CronJob from overlapping itself, but it
# does not know about a Job created by hand, and two indexers writing one
# volume is the condition this project already had an incident about.
running=$(kubectl -n "$NAMESPACE" get jobs \
  -o jsonpath='{range .items[?(@.status.active)]}{.metadata.name}{"\n"}{end}' 2>/dev/null \
  | grep -c indexer || true)
if [ "${running:-0}" -gt 0 ]; then
  echo "an indexer Job is already running in $NAMESPACE" >&2
  exit 1
fi

JOB="reindex-$(date -u +%Y%m%d-%H%M%S)"
kubectl -n "$NAMESPACE" create job --from="cronjob/$CRONJOB" "$JOB" >/dev/null
echo "created $JOB"

started=$(date +%s)
while :; do
  state=$(kubectl -n "$NAMESPACE" get job "$JOB" \
    -o jsonpath='{.status.succeeded} {.status.failed}' 2>/dev/null || true)
  succeeded=${state%% *}
  failed=${state##* }
  succeeded=${succeeded:-0}
  failed=${failed:-0}
  elapsed=$(( $(date +%s) - started ))
  if [ "$succeeded" -ge 1 ]; then
    echo "$JOB succeeded after ${elapsed}s"
    break
  fi
  if [ "$failed" -ge 1 ]; then
    echo "$JOB failed after ${elapsed}s" >&2
    exit 1
  fi
  if [ "$elapsed" -ge "$TIMEOUT_S" ]; then
    echo "$JOB unfinished after ${elapsed}s, limit ${TIMEOUT_S}s" >&2
    exit 1
  fi
  echo "$JOB running ${elapsed}s"
  sleep "$POLL_S"
done

# What the API sees afterwards. The indexer calls /api/lexical/refresh when it
# finishes, so a chunk count that moved and an index age near zero say the
# reopen worked, which is the thing the 2026-09-10 incident was about.
kubectl -n "$NAMESPACE" get pods \
  -l app.kubernetes.io/name=second-brain,app.kubernetes.io/component=api \
  -o custom-columns=POD:.metadata.name,READY:.status.containerStatuses[0].ready
