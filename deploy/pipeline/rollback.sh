#!/usr/bin/env bash
# Put one namespace's API back on its previous revision and say which image
# tag it landed on, so the caller can put that tag in the issue it opens.
#
#   bash deploy/pipeline/rollback.sh NAMESPACE
#
# This is the one script here that does not converge on a target: `rollout
# undo` swaps the Deployment's two newest revisions, so calling it twice puts
# back the image it just rolled away from. The pipeline calls it once, on the
# failed step, and the tag it prints is how a reader checks which way it went.
#
# It prints status words, counts and an image tag, nothing from the vault.
set -euo pipefail

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

DEPLOYMENT=second-brain
ROLLOUT_TIMEOUT=15m

if [ "$#" -ne 1 ]; then
  echo "usage: bash rollback.sh NAMESPACE" >&2
  exit 2
fi
NAMESPACE=$1

BEFORE=$(kubectl -n "$NAMESPACE" get "deployment/$DEPLOYMENT" \
  -o jsonpath='{.spec.template.spec.containers[0].image}')
echo "rolling back from ${BEFORE##*:}"

# A namespace with one revision has nothing to go back to. `rollout undo`
# says so and exits non-zero, which is the right answer: the caller asked for
# a rollback and did not get one.
kubectl -n "$NAMESPACE" rollout undo "deployment/$DEPLOYMENT"
kubectl -n "$NAMESPACE" rollout status "deployment/$DEPLOYMENT" --timeout="$ROLLOUT_TIMEOUT"

AFTER=$(kubectl -n "$NAMESPACE" get "deployment/$DEPLOYMENT" \
  -o jsonpath='{.spec.template.spec.containers[0].image}')
echo "rolled back to ${AFTER##*:}"

kubectl -n "$NAMESPACE" get pods \
  -l app.kubernetes.io/name=second-brain,app.kubernetes.io/component=api \
  -o custom-columns=POD:.metadata.name,IMAGE:.spec.containers[0].image,READY:.status.containerStatuses[0].ready
