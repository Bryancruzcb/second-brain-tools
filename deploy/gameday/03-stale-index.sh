#!/usr/bin/env bash
# Game-day scenario 3: rebuild the index while the API serves, and watch what
# that costs.
#
#   bash deploy/gameday/03-stale-index.sh NAMESPACE
#
# This is the incident this project already had, replayed on purpose. A
# long-lived API process held a Chroma view that another process wrote
# underneath it, and the API went on serving the old view; PR #25 fixed it by
# reopening the store when the write stamp moves. The nightly indexer is that
# second writer by design (deploy/k8s/base/cronjob-indexer.yaml), so the
# question this run answers is whether the reopen still holds, and what the
# rebuild costs the people querying while it runs.
#
# It creates a one-off Job from the indexer CronJob, and samples five things
# on a fixed interval while the Job runs and for one latency window
# afterwards:
#
#   * second_brain_index_age_seconds, which drops when the API reopens
#   * second_brain_collection_chunks, the size of the view being served
#   * the canary's hit rate against its recorded baseline
#   * search p95, which week 3 measured at 4.45 s during a full build and
#     1.97 s after it (deploy/monitoring/README.md)
#   * /api/ready?strict=1, which is what would take the pod out of service
#
# Search p95 only moves if somebody is searching. Between deploys the only
# traffic is the canary's ten questions every 15 minutes, so a quiet window
# samples as "absent" rather than as a number. Nothing here generates
# queries: a query string would have to come from somewhere, and the eval
# questions are private.
#
# It prints gauges, counts, HTTP codes and seconds, and deliberately never
# prints the indexer pod's logs: second-brain-config sets LOG_FORMAT=json, so
# one ordinary log line is a JSON object with string values, which
# output_guard.py refuses, and a refusal takes the whole step's output with
# it.
#
# exit 0  the rebuild finished, readiness held and the canary stayed at or
#         above its baseline
# exit 1  the rebuild failed or timed out, readiness dropped, or the canary
#         fell below its baseline
# exit 2  a bad argument
set -euo pipefail

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

. "$(dirname "$0")/lib.sh"

SCENARIO=03-stale-index
# The alert a rebuild is known to move. CanaryHitRateDropped is watched too
# and reported in the detail column, because only one alert fits the row.
ALERT=SearchLatencyHigh
INDEXER_CRONJOB=second-brain-indexer
# A unique name per run, so three runs of this scenario do not collide, and
# deliberately not `indexer-first`: deploy-namespace.sh treats that name as
# its own marker for an empty volume and would read this run's leftovers.
JOB="gameday-index-$(date -u +%Y%m%d%H%M%S)"
# 45 minutes, the same limit deploy-namespace.sh gives a first build and
# double the 22 minutes staging's 775-file build measured. A nightly
# incremental run is much shorter.
INDEX_TIMEOUT_S=2700
SAMPLE_S=60
# The p95 expression rates over 10 minutes, so a sample taken the second the
# build ends still carries the build's slow queries in its window. Sampling
# for one whole window afterwards is what makes the last sample the settled
# number rather than a leftover.
AFTER_WINDOW_S=600

if [ "$#" -ne 1 ]; then
  echo "usage: bash 03-stale-index.sh NAMESPACE" >&2
  exit 2
fi
NAMESPACE=$1

if ! kubectl -n "$NAMESPACE" get cronjob "$INDEXER_CRONJOB" >/dev/null 2>&1; then
  echo "no $INDEXER_CRONJOB cronjob in namespace $NAMESPACE" >&2
  exit 2
fi

prom_require

STARTED_UTC=$(utc_now)
SHA=$(short_sha "$(image_tag "$NAMESPACE")")
SERVICE_IP=$(api_service_ip "$NAMESPACE")

ACTIVE=$(indexer_active "$NAMESPACE")
if [ "$ACTIVE" -gt 0 ]; then
  echo "$ACTIVE indexer job(s) already running in $NAMESPACE; two writers on one volume is a different experiment" >&2
  exit 1
fi

# --- comparing samples that may not be numbers ------------------------------
# Every gauge here comes back either as a number or as "absent", so the two
# comparisons this run needs have to survive "absent" on either side.
numeric_max() {
  if [ "$2" = absent ] || [ "$2" = nan ]; then printf '%s' "$1"; return 0; fi
  if [ "$1" = absent ] || [ "$1" = nan ]; then printf '%s' "$2"; return 0; fi
  awk -v a="$1" -v b="$2" 'BEGIN { print (b > a) ? b : a }'
}

numeric_min() {
  if [ "$2" = absent ] || [ "$2" = nan ]; then printf '%s' "$1"; return 0; fi
  if [ "$1" = absent ] || [ "$1" = nan ]; then printf '%s' "$2"; return 0; fi
  awk -v a="$1" -v b="$2" 'BEGIN { print (b < a) ? b : a }'
}

# less_than A B: true only when both are numbers and A is below B. An absent
# reading is not evidence of a drop.
less_than() {
  case "$1 $2" in
    *absent*|*nan*) return 1 ;;
  esac
  awk -v a="$1" -v b="$2" 'BEGIN { exit !(a < b) }'
}

# --- one sample -------------------------------------------------------------
# Sets S_* rather than printing, so the loop can both print a line and keep
# the running maximum and minimum.
sample() {
  S_AGE=$(prom_value "max(second_brain_index_age_seconds{namespace=\"$NAMESPACE\"})" 0)
  S_CHUNKS=$(prom_value "max(second_brain_collection_chunks{namespace=\"$NAMESPACE\"})" 0)
  S_CANARY=$(prom_value "max(second_brain_canary_hit_rate{namespace=\"$NAMESPACE\"})")
  S_BASELINE=$(prom_value "max(second_brain_canary_baseline_hit_rate{namespace=\"$NAMESPACE\"})")
  S_P95=$(prom_value "histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{namespace=\"$NAMESPACE\", handler=\"/api/search\"}[10m])))")
  S_READY=$(api_strict_code "$SERVICE_IP")
  S_ALERT=$(alert_state "$ALERT" "$NAMESPACE")
  S_CANARY_ALERT=$(alert_state CanaryHitRateDropped "$NAMESPACE")
}

PENDING_S=none
FIRING_S=none
CLEAR_S=none
SEEN_ACTIVE=0

record_alert() {
  case "$2" in
    pending)
      SEEN_ACTIVE=1
      if [ "$PENDING_S" = none ]; then PENDING_S=$1; fi
      ;;
    firing)
      SEEN_ACTIVE=1
      if [ "$PENDING_S" = none ]; then PENDING_S=$1; fi
      if [ "$FIRING_S" = none ]; then FIRING_S=$1; fi
      ;;
    none)
      if [ "$SEEN_ACTIVE" -eq 1 ] && [ "$CLEAR_S" = none ]; then CLEAR_S=$1; fi
      ;;
  esac
}

P95_MAX=absent
AGE_MAX=absent
CANARY_MIN=absent
CANARY_ALERT=none
READY_NOT_200=0

accumulate() {
  P95_MAX=$(numeric_max "$P95_MAX" "$S_P95")
  AGE_MAX=$(numeric_max "$AGE_MAX" "$S_AGE")
  CANARY_MIN=$(numeric_min "$CANARY_MIN" "$S_CANARY")
  if [ "$S_READY" != 200 ]; then
    READY_NOT_200=$(( READY_NOT_200 + 1 ))
  fi
  if [ "$S_CANARY_ALERT" = firing ]; then
    CANARY_ALERT=firing
  elif [ "$S_CANARY_ALERT" = pending ] && [ "$CANARY_ALERT" = none ]; then
    CANARY_ALERT=pending
  fi
}

print_sample() {
  echo "t=${1}s job=$2 age=$S_AGE chunks=$S_CHUNKS canary=$S_CANARY base=$S_BASELINE p95=$S_P95 ready=$S_READY $ALERT=$S_ALERT"
}

# --- before -----------------------------------------------------------------
sample
echo "namespace $NAMESPACE sha $SHA job $JOB"
print_sample 0 none
AGE_BEFORE=$S_AGE
CHUNKS_BEFORE=$S_CHUNKS
P95_BEFORE=$S_P95
BASELINE=$S_BASELINE

# --- run the rebuild --------------------------------------------------------
kubectl -n "$NAMESPACE" create job --from="cronjob/$INDEXER_CRONJOB" "$JOB"
INJECTED_AT=$(now_s)

JOB_STATE=active
ELAPSED=0
while :; do
  ELAPSED=$(( $(now_s) - INJECTED_AT ))
  # One call for both counters, the way deploy-namespace.sh reads them: a
  # poll that costs two calls for 45 minutes is 90 calls for nothing.
  STATUS=$(kubectl -n "$NAMESPACE" get job "$JOB" \
    -o jsonpath='{.status.succeeded} {.status.failed}' 2>/dev/null || true)
  SUCCEEDED=${STATUS%% *}
  FAILED=${STATUS##* }
  SUCCEEDED=${SUCCEEDED:-0}
  FAILED=${FAILED:-0}
  if [ "$SUCCEEDED" -ge 1 ]; then
    JOB_STATE=succeeded
  elif [ "$FAILED" -ge 1 ]; then
    JOB_STATE=failed
  fi

  sample
  print_sample "$ELAPSED" "$JOB_STATE"
  record_alert "$ELAPSED" "$S_ALERT"
  accumulate

  if [ "$JOB_STATE" != active ]; then
    break
  fi
  if [ "$ELAPSED" -ge "$INDEX_TIMEOUT_S" ]; then
    JOB_STATE=timeout
    echo "$JOB unfinished after ${ELAPSED}s, limit ${INDEX_TIMEOUT_S}s" >&2
    break
  fi
  sleep "$SAMPLE_S"
done
BUILD_S=$ELAPSED
echo "$JOB $JOB_STATE after ${BUILD_S}s"

# --- one latency window afterwards ------------------------------------------
if [ "$JOB_STATE" = succeeded ]; then
  AFTER_STARTED=$(now_s)
  while :; do
    AFTER_ELAPSED=$(( $(now_s) - AFTER_STARTED ))
    sample
    print_sample "$(( BUILD_S + AFTER_ELAPSED ))" "$JOB_STATE"
    record_alert "$(( BUILD_S + AFTER_ELAPSED ))" "$S_ALERT"
    accumulate
    if [ "$AFTER_ELAPSED" -ge "$AFTER_WINDOW_S" ]; then
      break
    fi
    sleep "$SAMPLE_S"
  done
fi

AGE_AFTER=$S_AGE
CHUNKS_AFTER=$S_CHUNKS
P95_AFTER=$S_P95

# --- what it means ----------------------------------------------------------
if [ "$JOB_STATE" != succeeded ]; then
  OUTCOME=index-$JOB_STATE
elif [ "$READY_NOT_200" -gt 0 ]; then
  # The pod answered something other than 200 on the strict probe while the
  # rebuild ran, which is the shape the original incident had: a view that
  # stopped agreeing with the store underneath it.
  OUTCOME=indexed-unready
elif less_than "$CANARY_MIN" "$BASELINE"; then
  OUTCOME=indexed-degraded
else
  OUTCOME=indexed
fi

# A finished Job is deleted so three runs do not leave three behind; a failed
# one stays, because its pod is the only place to look at why.
if [ "$JOB_STATE" = succeeded ]; then
  kubectl -n "$NAMESPACE" delete job "$JOB" --wait=false
fi

DETAIL="chunks=${CHUNKS_BEFORE}->${CHUNKS_AFTER} age=${AGE_BEFORE}/${AGE_MAX}/${AGE_AFTER} p95=${P95_BEFORE}/${P95_MAX}/${P95_AFTER} canary_min=$CANARY_MIN base=$BASELINE canary_alert=$CANARY_ALERT not_200=$READY_NOT_200"

result_row "$SCENARIO" "$STARTED_UTC" "$NAMESPACE" "$SHA" "$ALERT" \
  "$PENDING_S" "$FIRING_S" "$BUILD_S" "$CLEAR_S" "$OUTCOME" "$DETAIL"

[ "$OUTCOME" = indexed ] || exit 1
