#!/usr/bin/env bash
# Install or update the monitoring stack on the node.
#
#   bash deploy/pipeline/deploy-monitoring.sh
#
# The stack is two HelmChart objects that k3s's own Helm controller installs
# (deploy/monitoring/), plus the alert rules, the dashboards and the bridge
# that turns an alert into a GitHub issue. This applies them and waits.
#
# It takes no namespace: monitoring is one stack for the whole node, and it
# scrapes both app namespaces.
#
# Until this existed the stack went on with a script that lived outside the
# repository, which made "destroy the environment and rebuild it" a step that
# could not be reproduced from what is committed. Every `ops.py down` takes
# the node and its monitoring with it, so a fresh node needs this again.
#
# It prints chart names, workload names, counts and status words.
set -euo pipefail

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

CHECKOUT=/opt/sbt
# The Helm controller runs one install Job per chart in kube-system, and the
# chart is not installed until that Job succeeds.
CHARTS="prometheus grafana"
CHART_TIMEOUT_S=600
CHART_POLL_S=10
# Grafana pulls its image and its provisioning sidecars on a fresh node.
ROLLOUT_TIMEOUT=10m
# The alert bridge only logs what it would post until the token is in
# Parameter Store, so it comes up either way and its absence is not a failure
# of this script (deploy/monitoring/README.md).
WORKLOADS="prometheus-server grafana alertmanager kube-state-metrics pushgateway alert-bridge"

echo "monitoring from $(git -C "$CHECKOUT" rev-parse --short HEAD)"

kubectl apply -k "$CHECKOUT/deploy/monitoring"

for chart in $CHARTS; do
  started=$(date +%s)
  while :; do
    state=$(kubectl -n kube-system get job "helm-install-$chart" \
      -o jsonpath='{.status.succeeded} {.status.failed}' 2>/dev/null || true)
    succeeded=${state%% *}
    failed=${state##* }
    succeeded=${succeeded:-0}
    failed=${failed:-0}
    elapsed=$(( $(date +%s) - started ))
    if [ "$succeeded" -ge 1 ]; then
      echo "$chart chart installed after ${elapsed}s"
      break
    fi
    if [ "$failed" -ge 1 ]; then
      echo "helm-install-$chart failed after ${elapsed}s" >&2
      exit 1
    fi
    if [ "$elapsed" -ge "$CHART_TIMEOUT_S" ]; then
      echo "helm-install-$chart unfinished after ${elapsed}s, limit ${CHART_TIMEOUT_S}s" >&2
      exit 1
    fi
    sleep "$CHART_POLL_S"
  done
done

# node-exporter is a DaemonSet and the two charts decide between Deployment
# and StatefulSet themselves, so each workload's kind is read rather than
# assumed.
for workload in $WORKLOADS; do
  kind=deployment
  for candidate in statefulset daemonset; do
    if kubectl -n monitoring get "$candidate" "$workload" >/dev/null 2>&1; then
      kind=$candidate
      break
    fi
  done
  kubectl -n monitoring rollout status "$kind/$workload" --timeout="$ROLLOUT_TIMEOUT"
done

echo "--- monitoring"
kubectl -n monitoring get pods \
  -o custom-columns=POD:.metadata.name,READY:.status.containerStatuses[*].ready,RESTARTS:.status.containerStatuses[*].restartCount \
  | cut -c1-200
