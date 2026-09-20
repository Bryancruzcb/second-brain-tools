#!/usr/bin/env bash
# What one namespace looks like right now, read-only.
#
#   bash deploy/pipeline/status.sh NAMESPACE
#
# The runbooks need a way to look at the cluster that changes nothing, and
# there is no kubectl on the desktop that reaches this node. This prints the
# fields a first look needs: the image each pod runs, whether it is Ready, how
# the last indexer and canary runs ended, how full the disk is, and what a
# failed pod's containers exited with.
#
# It deliberately does NOT print pod logs. The API's own logs can carry a
# query, and a query is a question about someone's notes. The two Jobs whose
# output is numbers by construction, the gate and the smoke test, are printed
# by run-job.sh, which is the script that creates them. Everything here is a
# kubectl field or a byte count.
set -euo pipefail

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

DEPLOYMENT=second-brain
# The volume the API and the indexer share, through local-path on the node's
# root disk, which is why the disk line below is the one that matters.
PVC=second-brain-data

if [ "$#" -ne 1 ]; then
  echo "usage: bash status.sh NAMESPACE" >&2
  exit 2
fi
NAMESPACE=$1

if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
  echo "no namespace $NAMESPACE" >&2
  exit 1
fi

echo "namespace $NAMESPACE"
echo "checkout $(git -C /opt/sbt rev-parse --short HEAD 2>/dev/null || echo none)"

echo "--- deployment"
kubectl -n "$NAMESPACE" get "deployment/$DEPLOYMENT" \
  -o custom-columns=READY:.status.readyReplicas,WANTED:.spec.replicas,IMAGE:.spec.template.spec.containers[0].image \
  2>/dev/null || echo "no deployment $DEPLOYMENT"

echo "--- pods"
# No NAME column beyond the generated suffix, which carries no information a
# reader needs and makes the line long. RESTARTS is the field that says a pod
# is crash-looping.
kubectl -n "$NAMESPACE" get pods \
  -o custom-columns=POD:.metadata.name,PHASE:.status.phase,READY:.status.containerStatuses[*].ready,RESTARTS:.status.containerStatuses[*].restartCount,IMAGE:.spec.containers[0].image \
  | cut -c1-200

echo "--- jobs, newest last"
kubectl -n "$NAMESPACE" get jobs \
  -o custom-columns=JOB:.metadata.name,SUCCEEDED:.status.succeeded,FAILED:.status.failed,COMPLETIONS:.status.completionTime \
  --sort-by=.metadata.creationTimestamp | cut -c1-200 | tail -8

echo "--- container exit codes on pods that are not Running"
# A Job that failed leaves its pod behind with the exit code on it. An init
# container that failed leaves containerStatuses empty, which is itself the
# answer, so both lists are printed.
kubectl -n "$NAMESPACE" get pods --field-selector=status.phase!=Running \
  -o jsonpath='{range .items[*]}{.metadata.name}{" init="}{.status.initContainerStatuses[*].state.terminated.exitCode}{" main="}{.status.containerStatuses[*].state.terminated.exitCode}{"\n"}{end}' \
  2>/dev/null | tail -8

echo "--- cronjobs"
kubectl -n "$NAMESPACE" get cronjobs \
  -o custom-columns=CRONJOB:.metadata.name,SCHEDULE:.spec.schedule,SUSPENDED:.spec.suspend,LAST:.status.lastSuccessfulTime \
  | cut -c1-200

echo "--- storage"
kubectl -n "$NAMESPACE" get "pvc/$PVC" \
  -o custom-columns=PVC:.metadata.name,PHASE:.status.phase,REQUESTED:.status.capacity.storage 2>/dev/null \
  || echo "no pvc $PVC"
# local-path volumes are directories on the root filesystem, so the PVC's
# requested size is not a limit and this is the number that matters. It is
# also what DiskAlmostFull watches.
df -h --output=source,size,used,pcent / | tail -1
