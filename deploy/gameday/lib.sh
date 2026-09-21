#!/usr/bin/env bash
# Shared helpers for the four game-day scenarios (docs/ops/PLAN.md 6.6).
#
# Sourced, never run:
#
#     . "$(dirname "$0")/lib.sh"
#
# It defines constants and functions only. Each scenario sets its own
# `set -euo pipefail` and KUBECONFIG, so sourcing this cannot change the
# caller's shell options, and the scenario that forgot them fails on its own
# first line rather than here.
#
# Three things here are worth reading before the scenarios themselves.
#
# **How the node reaches Prometheus.** These scripts run on the node's host
# network as root, where cluster DNS does not resolve: the in-cluster address
# http://prometheus-server.monitoring.svc.cluster.local:80 that every pod
# uses answers nothing from here. What does work is the Service's ClusterIP,
# because k3s programs the service range into the host's iptables, so the
# node can open ClusterIP:port directly. That is exactly how week 3's
# monitoring-status.sh, latency.sh and grafana-check.sh read Prometheus
# during the first live run on 2026-09-19, and prom_init below is the same
# two steps: read the ClusterIP with kubectl, then curl /api/v1/ on it. The
# same trick gives each namespace's API a reachable address without
# hardcoding the pinned 10.43.0.80 and .81.
#
# **What these may print.** The repository is public and the vault is not.
# Everything below prints counts, seconds, status words, alert names, HTTP
# codes and short SHAs. send_command.py refuses to print a whole command's
# output when any single line names a `.md` file, is not plain ASCII, runs
# over 300 characters, or is a JSON object carrying a string value
# (deploy/pipeline/output_guard.py). That last rule is why no scenario here
# prints an application pod's logs: second-brain-config sets
# LOG_FORMAT=json, so one ordinary log line would be a JSON object with
# string values and would take the whole step's output down with it.
#
# **Nothing is measured by sleeping and then asserting.** wait_for and the
# scenarios' own loops poll, count the elapsed seconds from a recorded
# instant, and say what they gave up on when a deadline passes. The sleeps
# in them are poll intervals, the same way run-job.sh waits for a Job.

# --- where things are -------------------------------------------------------
GAMEDAY_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
RESULTS_FILE="$GAMEDAY_DIR/results.tsv"
# Scenario 4 runs the pipeline's own gate script. Relative to this file
# rather than to /opt/sbt, so a checkout somewhere else still works.
PIPELINE_DIR="$GAMEDAY_DIR/../pipeline"

# --- names, all checked against the manifests -------------------------------
MONITORING_NAMESPACE=monitoring
PROM_SERVICE=prometheus-server            # deploy/monitoring/prometheus.yaml
DEPLOYMENT=second-brain                   # deploy/k8s/base/deployment.yaml
API_SELECTOR="app.kubernetes.io/name=second-brain,app.kubernetes.io/component=api"
INDEXER_SELECTOR="app.kubernetes.io/component=indexer"
API_PORT=8000
# Every HTTP call here is to an address on the node itself or on the cluster
# network, so a call that has not answered in ten seconds is a failure, not a
# slow network.
HTTP_TIMEOUT_S=10

# Set by prom_init. Empty means Prometheus was not found, and the readers
# below answer "absent" and "unknown" rather than failing: scenario 4 wants a
# number if there is one and does not depend on monitoring being up.
PROM_ADDR=""
# Set by wait_for, read by the caller that wants the seconds it waited.
WAITED_S=0

die() {
  echo "$*" >&2
  exit 1
}

now_s() {
  date +%s
}

utc_now() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

# --- Prometheus -------------------------------------------------------------
prom_init() {
  PROM_ADDR=$(kubectl -n "$MONITORING_NAMESPACE" get svc "$PROM_SERVICE" \
    -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)
  if [ -n "$PROM_ADDR" ]; then
    echo "prometheus at $PROM_ADDR"
  else
    echo "no $PROM_SERVICE service in $MONITORING_NAMESPACE" >&2
  fi
}

# For the scenarios whose whole measurement is an alert transition. Without
# Prometheus they would report "the alert never fired" when the truth is that
# nobody was watching.
prom_require() {
  prom_init
  [ -n "$PROM_ADDR" ] || die "this scenario measures an alert and needs Prometheus"
}

# prom_value EXPR [DECIMALS] -> the first sample's value, or "absent".
#
# curl is wrapped so a refused connection cannot kill the caller through
# pipefail: an empty body reaches python and comes back as "absent", which is
# a sample the run can carry on without.
prom_value() {
  if [ -z "$PROM_ADDR" ]; then
    echo absent
    return 0
  fi
  { curl -s -m "$HTTP_TIMEOUT_S" --get "http://$PROM_ADDR/api/v1/query" \
      --data-urlencode "query=$1" || true; } \
  | python3 -c '
import json, sys
places = int(sys.argv[1])
try:
    result = json.load(sys.stdin)["data"]["result"]
except Exception:
    result = []
if not result:
    print("absent")
else:
    print(("%." + str(places) + "f") % float(result[0]["value"][1]))
' "${2:-2}"
}

# alert_state NAME [NAMESPACE] -> firing | pending | none | unknown
#
# /api/v1/alerts lists active alerts only, so an alert that has gone away is
# simply absent, which is what "none" means here. "unknown" is a Prometheus
# that did not answer; callers treat it as "not yet", never as "cleared",
# because a scrape that failed is not evidence of health.
#
# An empty NAMESPACE matches any, which is what DiskAlmostFull needs: its
# expression aggregates over the whole node and carries no namespace label.
alert_state() {
  if [ -z "$PROM_ADDR" ]; then
    echo unknown
    return 0
  fi
  { curl -s -m "$HTTP_TIMEOUT_S" "http://$PROM_ADDR/api/v1/alerts" || true; } \
  | python3 -c '
import json, sys
name, namespace = sys.argv[1], sys.argv[2]
try:
    alerts = json.load(sys.stdin)["data"]["alerts"]
except Exception:
    print("unknown")
    sys.exit(0)
states = set()
for alert in alerts:
    labels = alert.get("labels", {})
    if labels.get("alertname") != name:
        continue
    if namespace and labels.get("namespace", "") != namespace:
        continue
    states.add(alert.get("state", ""))
print("firing" if "firing" in states else "pending" if "pending" in states else "none")
' "$1" "${2:-}"
}

# --- the API ----------------------------------------------------------------
api_ready_replicas() {
  local value
  value=$(kubectl -n "$1" get deployment "$DEPLOYMENT" \
    -o jsonpath='{.status.readyReplicas}' 2>/dev/null || true)
  echo "${value:-0}"
}

# The Service's own ClusterIP rather than the pinned 10.43.0.80 and .81 from
# the overlays: read at run time it is right for any namespace, and it cannot
# go stale against ops.py's table.
api_service_ip() {
  kubectl -n "$1" get svc "$DEPLOYMENT" -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true
}

# api_strict_code SERVICE_IP -> the HTTP code from /api/ready?strict=1, or 000.
#
# strict=1 is the probe contract: 503 until every component has loaded and the
# collection holds at least one chunk (deploy/k8s/base/deployment.yaml). Plain
# /api/ready answers 200 with a component map and would call an empty index
# healthy.
api_strict_code() {
  local code
  if [ -z "$1" ]; then
    printf '000'
    return 0
  fi
  code=$(curl -s -m "$HTTP_TIMEOUT_S" -o /dev/null -w '%{http_code}' \
    "http://$1:$API_PORT/api/ready?strict=1" 2>/dev/null) || code=000
  printf '%s' "$code"
}

# The image tag the namespace is actually serving, which is the commit the
# pipeline pinned. Reading it from the Deployment rather than from `git -C
# /opt/sbt rev-parse HEAD` matters: the checkout is at whatever commit this
# command was sent with, which need not be what is running.
image_tag() {
  local image
  image=$(kubectl -n "$1" get deployment "$DEPLOYMENT" \
    -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || true)
  printf '%s' "${image##*:}"
}

short_sha() {
  printf '%s' "${1:0:12}"
}

# --- the indexer ------------------------------------------------------------
# How many indexer Jobs have a running pod, in one namespace or in all of
# them. Scenarios 2 and 3 refuse to start while one is going: filling the root
# volume under a rebuild, or starting a second rebuild beside the first, turns
# a timed experiment into a real incident on the volume both share.
indexer_active() {
  local scope
  if [ -n "${1:-}" ]; then
    scope=(-n "$1")
  else
    scope=(-A)
  fi
  kubectl "${scope[@]}" get jobs -l "$INDEXER_SELECTOR" \
    -o jsonpath='{range .items[*]}{.status.active}{"\n"}{end}' 2>/dev/null \
    | grep -c '^[1-9]' || true
}

# --- waiting ----------------------------------------------------------------
# wait_for DESCRIPTION SINCE DEADLINE_S POLL_S COMMAND...
#
# Polls COMMAND until it succeeds. The deadline is counted from SINCE, an
# epoch second the caller recorded when it injected the fault, so the number
# this reports is time-to-recovery and not time-spent-in-this-function. Sets
# WAITED_S either way and returns 1 on the deadline, with a line saying what
# it gave up on.
wait_for() {
  local desc=$1 since=$2 deadline=$3 poll=$4
  shift 4
  while :; do
    if "$@"; then
      WAITED_S=$(( $(now_s) - since ))
      echo "$desc after ${WAITED_S}s"
      return 0
    fi
    WAITED_S=$(( $(now_s) - since ))
    if [ "$WAITED_S" -ge "$deadline" ]; then
      echo "gave up waiting for $desc after ${WAITED_S}s, limit ${deadline}s" >&2
      return 1
    fi
    sleep "$poll"
  done
}

# --- the result row ---------------------------------------------------------
# result_row FIELD...
#
# The node's checkout is thrown away after the run, so nothing here writes
# results.tsv. This prints the header and the row under it, and the operator
# copies the row into the file in the repository.
#
# The header is read out of results.tsv in this same checkout rather than
# copied into a constant here, so the two cannot drift: add a column to the
# file without adding a field at the call site and the scenario stops with a
# message instead of printing a row that lines up with nothing.
result_row() {
  local header columns
  [ -f "$RESULTS_FILE" ] || die "no results.tsv beside $GAMEDAY_DIR"
  header=$(head -n 1 "$RESULTS_FILE")
  columns=$(printf '%s' "$header" | awk -F'\t' '{print NF}')
  if [ "$#" -ne "$columns" ]; then
    die "result row has $# fields, the results.tsv header has $columns"
  fi
  echo "--- result row: copy the last line into deploy/gameday/results.tsv"
  printf '%s\n' "$header"
  printf '%s' "$1"
  shift
  printf '\t%s' "$@"
  printf '\n'
}
