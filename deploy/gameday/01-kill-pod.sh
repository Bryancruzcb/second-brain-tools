#!/usr/bin/env bash
# Game-day scenario 1: delete the API pod and watch Kubernetes put it back.
#
#   bash deploy/gameday/01-kill-pod.sh NAMESPACE
#
# The question is not whether the pod comes back, it is how long the namespace
# has no API and whether that gap is long enough to be worth waking someone
# for. One replica per namespace means a deleted pod is a real outage until
# the replacement passes /api/ready?strict=1, and ApiNotReady is the alert
# that would page: it is `for: 5m`, so a restart under a minute should leave
# it pending and never firing.
#
# That is the expectation, not an assertion. This watches for 420 seconds,
# which is past the 5 minutes ApiNotReady needs, and reports both transitions
# it saw. An alert that did fire is the finding, and this exits non-zero.
#
# It prints pod names, HTTP codes, alert names, status words and seconds. It
# never reads a note, a note path or an eval question: this repository is
# public and the vault is not.
#
# exit 0  the API came back and ApiNotReady never reached firing
# exit 1  it did not come back inside the deadline, the alert fired, or the
#         alert was already active before the run
# exit 2  a bad argument
set -euo pipefail

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

. "$(dirname "$0")/lib.sh"

SCENARIO=01-kill-pod
ALERT=ApiNotReady
# ApiNotReady is `for: 5m` (deploy/monitoring/rules/second-brain.yml), so it
# cannot reach firing before 300 seconds whatever happens. 420 covers that
# plus four of Prometheus's 30-second evaluation intervals, which is what
# makes "it did not fire" a measurement rather than "we stopped looking".
WATCH_S=420
# PLAN.md section 6.6 expects recovery in under a minute. Three minutes is
# where this stops being an experiment and becomes an outage the operator
# should look at, so the run ends and says so.
RECOVERY_DEADLINE_S=180
# One kubectl call and one Prometheus call per poll, against a 30-second
# scrape interval: ten seconds is fine-grained enough to place a transition
# and cheap enough to run for seven minutes.
POLL_S=10

if [ "$#" -ne 1 ]; then
  echo "usage: bash 01-kill-pod.sh NAMESPACE" >&2
  exit 2
fi
NAMESPACE=$1

if ! kubectl -n "$NAMESPACE" get deployment "$DEPLOYMENT" >/dev/null 2>&1; then
  echo "no $DEPLOYMENT deployment in namespace $NAMESPACE" >&2
  exit 2
fi

prom_require

STARTED_UTC=$(utc_now)
SHA=$(short_sha "$(image_tag "$NAMESPACE")")
SERVICE_IP=$(api_service_ip "$NAMESPACE")

# The pod that is about to go. The Deployment runs one, but take the newest
# so a run started during a rollout kills the pod that is actually serving.
OLD_POD=$(kubectl -n "$NAMESPACE" get pods -l "$API_SELECTOR" \
  --sort-by=.metadata.creationTimestamp -o name 2>/dev/null | tail -n 1 || true)
OLD_POD=${OLD_POD#*/}
if [ -z "$OLD_POD" ]; then
  echo "no API pod in $NAMESPACE to delete" >&2
  exit 1
fi

echo "namespace $NAMESPACE sha $SHA pod $OLD_POD"
echo "before: ready $(api_ready_replicas "$NAMESPACE") strict $(api_strict_code "$SERVICE_IP")"

# An alert that is already pending or firing makes every number below
# meaningless: the transition this wants to time has already happened, for a
# reason that has nothing to do with the pod about to be deleted.
PRE_STATE=$(alert_state "$ALERT" "$NAMESPACE")
if [ "$PRE_STATE" != none ]; then
  echo "$ALERT is already $PRE_STATE in $NAMESPACE, so there is nothing to time" >&2
  exit 1
fi

# The replacement is serving once the Deployment reports a ready replica and
# the old pod is gone from the API server. Both halves matter: readyReplicas
# alone still counts the old pod in its first seconds, and the old pod's
# disappearance alone says nothing about the new one.
new_pod_ready() {
  [ "$(api_ready_replicas "$NAMESPACE")" -ge 1 ] || return 1
  ! kubectl -n "$NAMESPACE" get pod "$OLD_POD" >/dev/null 2>&1
}

INJECTED_AT=$(now_s)
kubectl -n "$NAMESPACE" delete pod "$OLD_POD" --wait=false
echo "deleted $OLD_POD"

# --- one loop, both measurements --------------------------------------------
# The alert and the recovery are sampled in the same loop on purpose. Waiting
# for the pod first and then starting to watch the alert would miss a pending
# that came and went during the restart, which is the transition this
# scenario exists to measure.
PENDING_S=none
FIRING_S=none
RECOVERY_S=none
CLEAR_S=none
SEEN_ACTIVE=0
LAST_STATE=""
ELAPSED=0

while :; do
  ELAPSED=$(( $(now_s) - INJECTED_AT ))
  STATE=$(alert_state "$ALERT" "$NAMESPACE")

  if [ "$STATE" != "$LAST_STATE" ]; then
    echo "t=${ELAPSED}s $ALERT $STATE"
    LAST_STATE=$STATE
  fi

  case "$STATE" in
    pending)
      SEEN_ACTIVE=1
      if [ "$PENDING_S" = none ]; then PENDING_S=$ELAPSED; fi
      ;;
    firing)
      SEEN_ACTIVE=1
      # A firing alert this run never saw pending means the poll landed
      # between the two; pending is no later than firing either way.
      if [ "$PENDING_S" = none ]; then PENDING_S=$ELAPSED; fi
      if [ "$FIRING_S" = none ]; then FIRING_S=$ELAPSED; fi
      ;;
    none)
      if [ "$SEEN_ACTIVE" -eq 1 ] && [ "$CLEAR_S" = none ]; then CLEAR_S=$ELAPSED; fi
      ;;
  esac

  if [ "$RECOVERY_S" = none ] && new_pod_ready; then
    RECOVERY_S=$ELAPSED
    echo "t=${ELAPSED}s API ready again, strict $(api_strict_code "$SERVICE_IP")"
  fi

  if [ "$RECOVERY_S" = none ] && [ "$ELAPSED" -ge "$RECOVERY_DEADLINE_S" ]; then
    echo "the API in $NAMESPACE has not been ready for ${ELAPSED}s, limit ${RECOVERY_DEADLINE_S}s" >&2
    break
  fi
  if [ "$ELAPSED" -ge "$WATCH_S" ]; then
    break
  fi
  sleep "$POLL_S"
done

if [ "$RECOVERY_S" = none ]; then
  OUTCOME=not-recovered
elif [ "$FIRING_S" != none ]; then
  OUTCOME=recovered-fired
else
  OUTCOME=recovered
fi

echo "watched $ALERT for ${ELAPSED}s: pending $PENDING_S firing $FIRING_S clear $CLEAR_S"
DETAIL="watch=${WATCH_S}s strict=$(api_strict_code "$SERVICE_IP") ready=$(api_ready_replicas "$NAMESPACE")"

result_row "$SCENARIO" "$STARTED_UTC" "$NAMESPACE" "$SHA" "$ALERT" \
  "$PENDING_S" "$FIRING_S" "$RECOVERY_S" "$CLEAR_S" "$OUTCOME" "$DETAIL"

[ "$OUTCOME" = recovered ] || exit 1
