#!/usr/bin/env bash
# Game-day scenario 4: break retrieval on purpose and check that the gate
# refuses to promote it.
#
#   bash deploy/gameday/04-bad-config.sh NAMESPACE
#
# PLAN.md section 6.6 describes this as a deploy of a branch whose config
# breaks retrieval, "for example a top k of 1". The break does not need a
# branch: TOP_K lives in the second-brain-config ConfigMap
# (deploy/k8s/base/configmap.yaml), pinned at 8, and every pod reads it
# through envFrom at start. Setting it to 1 and restarting the Deployment
# gives the same broken API the branch would have, on the image already
# running, and leaves nothing behind in git.
#
# The gate then runs exactly as the pipeline runs it, through
# deploy/pipeline/run-job.sh, so what this measures is the gate the deploy
# actually uses and not a second copy of it. A top k of 1 serves one chunk
# per query, so the recorded hit rate should drop well past drift_verdict's
# five-point rule and the gate should exit 1.
#
# Putting the ConfigMap back is not optional, so the restore runs from an
# EXIT trap as well as on the ordinary path: a namespace left at TOP_K=1
# serves bad answers until somebody notices.
#
# Two things about running this. Prefer staging: the gate's whole purpose is
# to stop a bad image before prod, and a restart in prod is a real outage of
# the thing the canary watches. And the rolling restart brings up a second
# API pod before the first goes (maxUnavailable 0), which wants about 900 MiB
# free on the node, so not at 06:00 UTC when both indexers run.
#
# It prints status words, exit codes, seconds and one hit rate. It never
# prints a note, a note path or an eval question. Note that the gate's own
# output passes through here unchanged: run-job.sh prints the gate pod's
# logs, which http_eval has already checked with private_keys_found.
#
# exit 0  the gate reported drift, which is the expectation
# exit 1  the gate passed a broken config, had no card to compare against,
#         refused its own summary, or something failed
# exit 2  a bad argument
set -euo pipefail

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

. "$(dirname "$0")/lib.sh"

SCENARIO=04-bad-config
CONFIGMAP=second-brain-config
KEY=TOP_K
# One chunk per query. The recorded card was measured at TOP_K=8, so this is
# far past the gate's five-point drift rule rather than near it: a scenario
# that only just trips the gate proves less than one that clearly should.
BROKEN_VALUE=1
GATE_TEMPLATE=deploy/k8s/gate-job.yaml
GATE_JOBNAME=gameday-gate
# The API is unready while its models load, which the readiness probe allows
# ten minutes for; the same limit the pipeline's own rollouts use.
ROLLOUT_TIMEOUT=15m
READY_DEADLINE_S=900
READY_POLL_S=10

if [ "$#" -ne 1 ]; then
  echo "usage: bash 04-bad-config.sh NAMESPACE" >&2
  exit 2
fi
NAMESPACE=$1

if ! kubectl -n "$NAMESPACE" get deployment "$DEPLOYMENT" >/dev/null 2>&1; then
  echo "no $DEPLOYMENT deployment in namespace $NAMESPACE" >&2
  exit 2
fi
if [ ! -f "$PIPELINE_DIR/run-job.sh" ]; then
  echo "no run-job.sh in $PIPELINE_DIR" >&2
  exit 2
fi

# run-job.sh wants the 40-hex tag the pipeline pinned, and the gate has to
# score the image the namespace is really serving. A tag that is not a commit
# means the namespace was applied without pinning one, and there is nothing
# here worth gating.
TAG=$(image_tag "$NAMESPACE")
if ! printf '%s' "$TAG" | grep -Eq '^[0-9a-f]{40}$'; then
  echo "the $DEPLOYMENT image in $NAMESPACE is tagged '$TAG', not a commit" >&2
  exit 2
fi
SHA=$(short_sha "$TAG")

# Prometheus is a nice-to-have here: this scenario's signal is the gate's
# exit code, and the canary reading below is context, not a verdict.
prom_init

STARTED_UTC=$(utc_now)

ORIGINAL=$(kubectl -n "$NAMESPACE" get configmap "$CONFIGMAP" \
  -o jsonpath="{.data.$KEY}" 2>/dev/null || true)
if [ -z "$ORIGINAL" ]; then
  echo "$CONFIGMAP in $NAMESPACE has no $KEY to restore, so this will not change it" >&2
  exit 1
fi
if [ "$ORIGINAL" = "$BROKEN_VALUE" ]; then
  echo "$KEY is already $BROKEN_VALUE in $NAMESPACE, which is the broken value" >&2
  exit 1
fi
echo "namespace $NAMESPACE sha $SHA $KEY $ORIGINAL"

set_key() {
  kubectl -n "$NAMESPACE" patch configmap "$CONFIGMAP" --type merge \
    -p "{\"data\":{\"$KEY\":\"$1\"}}" >/dev/null
}

api_ready() {
  [ "$(api_ready_replicas "$NAMESPACE")" -ge 1 ]
}

# CHANGED is the trap's whole state. The ordinary path restores and clears
# it, so the trap is a no-op by the time it runs; every other path leaves it
# set and the trap does the work.
CHANGED=0
restore() {
  if [ "$CHANGED" -eq 1 ]; then
    echo "restoring $KEY=$ORIGINAL in $NAMESPACE"
    set_key "$ORIGINAL" || echo "could not restore $KEY in $NAMESPACE, do it by hand" >&2
    kubectl -n "$NAMESPACE" rollout restart "deployment/$DEPLOYMENT" || true
    kubectl -n "$NAMESPACE" rollout status "deployment/$DEPLOYMENT" --timeout="$ROLLOUT_TIMEOUT" || true
    CHANGED=0
  fi
  return 0
}
trap restore EXIT
trap 'restore; exit 1' INT TERM

# --- break it ---------------------------------------------------------------
CHANGED=1
BROKE_AT=$(now_s)
set_key "$BROKEN_VALUE"
APPLIED=$(kubectl -n "$NAMESPACE" get configmap "$CONFIGMAP" -o jsonpath="{.data.$KEY}")
if [ "$APPLIED" != "$BROKEN_VALUE" ]; then
  echo "$KEY is $APPLIED after the patch, not $BROKEN_VALUE" >&2
  exit 1
fi
echo "$KEY set to $BROKEN_VALUE"

# envFrom is read once, when the container starts, so the ConfigMap alone
# changes nothing until the pods are replaced.
kubectl -n "$NAMESPACE" rollout restart "deployment/$DEPLOYMENT"
kubectl -n "$NAMESPACE" rollout status "deployment/$DEPLOYMENT" --timeout="$ROLLOUT_TIMEOUT"
BROKEN_READY_S=$(( $(now_s) - BROKE_AT ))
echo "serving $KEY=$BROKEN_VALUE after ${BROKEN_READY_S}s"

# --- the gate, the way the pipeline runs it ---------------------------------
GATE_CODE=0
bash "$PIPELINE_DIR/run-job.sh" "$NAMESPACE" "$TAG" "$GATE_TEMPLATE" "$GATE_JOBNAME" || GATE_CODE=$?
GATE_S=$(( $(now_s) - BROKE_AT ))
echo "gate exit $GATE_CODE after ${GATE_S}s"

case "$GATE_CODE" in
  0) OUTCOME=no-drift ;;      # the gate passed a config that serves one chunk
  1) OUTCOME=drift ;;         # EXIT_DRIFT, the expectation
  2) OUTCOME=gate-refused ;;  # the summary tripped private_keys_found
  3) OUTCOME=no-card ;;       # no recorded scorecard to compare against yet
  *) OUTCOME=gate-error ;;
esac

# The canary runs every 15 minutes, so this reading is whatever its last run
# scored, which may be from before the break. It is context for the row, not
# the verdict.
CANARY=$(prom_value "max(second_brain_canary_hit_rate{namespace=\"$NAMESPACE\"})")
BASELINE=$(prom_value "max(second_brain_canary_baseline_hit_rate{namespace=\"$NAMESPACE\"})")

# --- put it back ------------------------------------------------------------
RESTORE_STARTED=$(now_s)
restore
if wait_for "the API ready on $KEY=$ORIGINAL" "$BROKE_AT" "$(( GATE_S + READY_DEADLINE_S ))" "$READY_POLL_S" api_ready; then
  RECOVERY_S=$WAITED_S
else
  RECOVERY_S=none
  OUTCOME=not-restored
fi
RESTORE_S=$(( $(now_s) - RESTORE_STARTED ))

FINAL=$(kubectl -n "$NAMESPACE" get configmap "$CONFIGMAP" -o jsonpath="{.data.$KEY}" 2>/dev/null || true)
echo "$KEY is $FINAL, strict $(api_strict_code "$(api_service_ip "$NAMESPACE")")"
if [ "$FINAL" != "$ORIGINAL" ]; then
  echo "$KEY is $FINAL and should be $ORIGINAL; fix it before anything else" >&2
  OUTCOME=not-restored
fi

DETAIL="gate_exit=$GATE_CODE ${KEY}=${ORIGINAL}->${BROKEN_VALUE}->${FINAL} broken_ready=${BROKEN_READY_S}s restore=${RESTORE_S}s canary=$CANARY base=$BASELINE"

result_row "$SCENARIO" "$STARTED_UTC" "$NAMESPACE" "$SHA" "-" \
  "none" "none" "$RECOVERY_S" "none" "$OUTCOME" "$DETAIL"

[ "$OUTCOME" = drift ] || exit 1
