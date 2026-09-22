#!/usr/bin/env bash
# Game-day scenario 2: fill the node's root volume, wait for DiskAlmostFull,
# then take the space back and watch the alert clear.
#
#   bash deploy/gameday/02-fill-disk.sh
#
# The root volume is the whole machine here: k3s, the container images, both
# namespaces' local-path volumes with the vault copy and the Chroma index,
# and Prometheus's data all sit on the same 30 GB disk. That is why
# DiskAlmostFull exists, and why this scenario is the one with a blast
# radius. A volume filled to 100 percent stops k3s and the SSM agent, and an
# SSM agent that cannot run a command is an agent that cannot be told to
# clean up: the node would have to be destroyed and rebuilt.
#
# So the filler is sized from the real free space, never from a guess:
#
#   * it targets a point between DiskAlmostFull's 80 percent line and the
#     kubelet's first reaction, and it reads the kubelet's lines live
#     rather than trusting a number (see TARGET_USED_PCT);
#   * it never leaves less than MIN_FREE_BYTES free, whatever that target
#     works out to on a bigger or smaller disk;
#   * it refuses to run at all when the disk is already past the alert's own
#     threshold, because then the alert is telling the truth about a real
#     problem and this would make it worse;
#   * it refuses when an indexer Job is running, because a rebuild that runs
#     out of space mid-write is a real corrupted index, not an experiment;
#   * and it removes the filler from an EXIT trap, so an error, a Ctrl-C or
#     an SSM timeout that sends a signal still gives the space back.
#
# df's Avail already excludes the blocks ext4 reserves for root, and so does
# the node_filesystem_avail_bytes the alert reads, so the two agree and the
# real floor is higher than the one computed here.
#
# It prints percentages, byte counts, alert names and seconds.
#
# exit 0  DiskAlmostFull fired and cleared again after the filler went
# exit 1  it never fired, it never cleared, or the run refused to start
# exit 2  a bad argument
set -euo pipefail

export KUBECONFIG=/etc/rancher/k3s/k3s.yaml

. "$(dirname "$0")/lib.sh"

SCENARIO=02-fill-disk
ALERT=DiskAlmostFull
# /var/tmp is on the root volume, which is the filesystem the alert watches
# (mountpoint "/"), and unlike /tmp it is not a tmpfs, so the bytes land on
# the disk rather than in RAM. Nothing else on the node uses this name.
FILLER=/var/tmp/second-brain-gameday-filler
# Between the alert and the kubelet. PLAN.md section 6.6 asked for 95
# percent, and the first run on 2026-09-22 showed why that is wrong on this
# node: k3s's kubelet evicts pods once free space falls under 5 percent,
# which is 95 percent used, and it deletes unused images from 85 percent
# back down to 80. That run evicted both API pods and Grafana, tainted the
# node NoSchedule for five minutes after the space came back, and fired
# ApiNotReady in both namespaces, while DiskAlmostFull never fired at all:
# image GC pulled the disk under 80 percent within a minute. So the target
# is above the alert's 80 and below image GC's 85, and the two kubelet lines
# are checked against the live kubelet config before anything is allocated.
TARGET_USED_PCT=83
# The safety margin, in bytes rather than in percent so it does not shrink
# with the disk. On the 30 GB root volume the 83 percent target leaves about
# 5 GB, so this floor only takes over on a much smaller disk.
MIN_FREE_BYTES=1073741824
# Below this there is nothing worth doing: the disk is already close enough
# to the target that the filler would be noise, and the margin above is
# doing all the work.
MIN_FILLER_BYTES=268435456
# DiskAlmostFull's own line is 80 percent. Past it, the alert is already
# reporting a real problem.
REFUSE_ABOVE_USED_PCT=80
# DiskAlmostFull is `for: 10m`, so firing cannot happen before 600 seconds.
# 900 adds five of Prometheus's 30-second evaluation intervals plus the
# node-exporter scrape that has to see the smaller number first.
WATCH_S=900
# Removing the filler makes the expression false at the next evaluation, so
# the alert should disappear within a scrape and an evaluation. Five minutes
# is far past that and still bounded.
CLEAR_DEADLINE_S=300
POLL_S=15

if [ "$#" -ne 0 ]; then
  echo "usage: bash 02-fill-disk.sh" >&2
  exit 2
fi

prom_require

STARTED_UTC=$(utc_now)
# This scenario is about the node, not a namespace, and DiskAlmostFull
# aggregates over the whole node and carries no namespace label. The commit
# is the one the checkout is on, which is what the operator sent.
SHA=$(short_sha "$(git -C "$GAMEDAY_DIR" rev-parse HEAD 2>/dev/null || echo unknown)")

ACTIVE=$(indexer_active "")
if [ "$ACTIVE" -gt 0 ]; then
  echo "$ACTIVE indexer job(s) running; filling the volume under a rebuild is a real incident" >&2
  exit 1
fi

PRE_STATE=$(alert_state "$ALERT" "")
if [ "$PRE_STATE" != none ]; then
  echo "$ALERT is already $PRE_STATE, so there is nothing to time" >&2
  exit 1
fi

# --- the kubelet's own lines, read live ---------------------------------------
# Past image GC's high line the kubelet deletes images until the disk is back
# under the alert, so the scenario would measure nothing; past the eviction
# line it takes the API down. A config that cannot be read, or an eviction
# threshold that is not a percentage, is a refusal rather than a guess.
NODE=$(kubectl get node -o jsonpath='{.items[0].metadata.name}')
read -r GC_HIGH_PCT EVICT_FREE_PCT <<<"$(kubectl get --raw "/api/v1/nodes/$NODE/proxy/configz" 2>/dev/null \
  | python3 -c '
import json, sys
c = json.load(sys.stdin)["kubeletconfig"]
free = str((c.get("evictionHard") or {}).get("nodefs.available", ""))
print(int(c.get("imageGCHighThresholdPercent") or 0), free[:-1] if free.endswith("%") else 0)
' 2>/dev/null || echo "0 0")"
if [ "${GC_HIGH_PCT:-0}" -le 0 ] || [ "${EVICT_FREE_PCT:-0}" -le 0 ]; then
  echo "refusing: could not read the kubelet's image GC and eviction thresholds" >&2
  exit 1
fi
echo "kubelet: deletes images from ${GC_HIGH_PCT}% used, evicts pods under ${EVICT_FREE_PCT}% free"
if [ "$TARGET_USED_PCT" -ge "$GC_HIGH_PCT" ]; then
  echo "refusing: a ${TARGET_USED_PCT}% target is at or past the kubelet's image GC line, ${GC_HIGH_PCT}%" >&2
  exit 1
fi
if [ $(( 100 - TARGET_USED_PCT )) -le "$EVICT_FREE_PCT" ]; then
  echo "refusing: a ${TARGET_USED_PCT}% target leaves no more free than the kubelet's eviction line, ${EVICT_FREE_PCT}%" >&2
  exit 1
fi

# --- size the filler from what is really free -------------------------------
read -r SIZE_B AVAIL_B <<<"$(df -B1 --output=size,avail / | tail -n 1)"
USED_PCT_BEFORE=$(( (SIZE_B - AVAIL_B) * 100 / SIZE_B ))
TARGET_AVAIL_B=$(( SIZE_B * (100 - TARGET_USED_PCT) / 100 ))
if [ "$TARGET_AVAIL_B" -lt "$MIN_FREE_BYTES" ]; then
  TARGET_AVAIL_B=$MIN_FREE_BYTES
fi
FILLER_B=$(( AVAIL_B - TARGET_AVAIL_B ))

echo "root volume ${USED_PCT_BEFORE}% used, target ${TARGET_USED_PCT}%, floor $(( MIN_FREE_BYTES / 1048576 )) MiB free"

if [ "$USED_PCT_BEFORE" -ge "$REFUSE_ABOVE_USED_PCT" ]; then
  echo "refusing: the volume is already ${USED_PCT_BEFORE}% used, at or past the ${REFUSE_ABOVE_USED_PCT}% alert line" >&2
  exit 1
fi
if [ "$FILLER_B" -lt "$MIN_FILLER_BYTES" ]; then
  echo "refusing: a safe filler would be $(( FILLER_B / 1048576 )) MiB, under the $(( MIN_FILLER_BYTES / 1048576 )) MiB minimum" >&2
  exit 1
fi

# --- the trap, set before anything is allocated -----------------------------
remove_filler() {
  if [ -e "$FILLER" ]; then
    rm -f "$FILLER"
    echo "filler removed"
  fi
  return 0
}
# EXIT covers the ordinary and the failing paths; INT and TERM matter because
# SSM signals the command when its execution timeout passes, and a filler
# left behind on a node with no shell is the one failure mode worth two
# lines of trap.
trap remove_filler EXIT
trap 'remove_filler; exit 1' INT TERM

echo "allocating $(( FILLER_B / 1048576 )) MiB"
# fallocate reserves the blocks without writing them, which is what statfs
# and so node-exporter count, and it takes a moment rather than minutes. dd
# is the fallback for a filesystem that cannot preallocate.
if ! fallocate -l "$FILLER_B" "$FILLER" 2>/dev/null; then
  echo "fallocate unavailable, writing the blocks instead"
  dd if=/dev/zero of="$FILLER" bs=1M count=$(( FILLER_B / 1048576 )) status=none
fi
INJECTED_AT=$(now_s)

read -r SIZE_B AVAIL_FILLED_B <<<"$(df -B1 --output=size,avail / | tail -n 1)"
USED_PCT_FILLED=$(( (SIZE_B - AVAIL_FILLED_B) * 100 / SIZE_B ))
echo "root volume now ${USED_PCT_FILLED}% used, $(( AVAIL_FILLED_B / 1048576 )) MiB free"
if [ "$USED_PCT_FILLED" -le "$REFUSE_ABOVE_USED_PCT" ]; then
  echo "the filler left the volume at ${USED_PCT_FILLED}%, which is not past the ${REFUSE_ABOVE_USED_PCT}% line" >&2
  exit 1
fi

# --- wait for the alert -----------------------------------------------------
PENDING_S=none
FIRING_S=none
RECOVERY_S=none
CLEAR_S=none
LAST_STATE=""
ELAPSED=0

while :; do
  ELAPSED=$(( $(now_s) - INJECTED_AT ))
  STATE=$(alert_state "$ALERT" "")

  if [ "$STATE" != "$LAST_STATE" ]; then
    echo "t=${ELAPSED}s $ALERT $STATE"
    LAST_STATE=$STATE
  fi

  case "$STATE" in
    pending)
      if [ "$PENDING_S" = none ]; then PENDING_S=$ELAPSED; fi
      ;;
    firing)
      if [ "$PENDING_S" = none ]; then PENDING_S=$ELAPSED; fi
      if [ "$FIRING_S" = none ]; then FIRING_S=$ELAPSED; fi
      ;;
  esac

  if [ "$FIRING_S" != none ]; then
    break
  fi
  if [ "$ELAPSED" -ge "$WATCH_S" ]; then
    echo "$ALERT did not fire in ${ELAPSED}s, limit ${WATCH_S}s, with the volume at ${USED_PCT_FILLED}%" >&2
    break
  fi
  sleep "$POLL_S"
done

# --- give the space back and watch it clear ---------------------------------
remove_filler
RECOVERY_S=$(( $(now_s) - INJECTED_AT ))
read -r SIZE_B AVAIL_AFTER_B <<<"$(df -B1 --output=size,avail / | tail -n 1)"
USED_PCT_AFTER=$(( (SIZE_B - AVAIL_AFTER_B) * 100 / SIZE_B ))
echo "root volume back to ${USED_PCT_AFTER}% used after ${RECOVERY_S}s"

alert_gone() {
  [ "$(alert_state "$ALERT" "")" = none ]
}

if [ "$FIRING_S" = none ]; then
  OUTCOME=no-alert
elif wait_for "$ALERT cleared" "$INJECTED_AT" "$(( RECOVERY_S + CLEAR_DEADLINE_S ))" "$POLL_S" alert_gone; then
  CLEAR_S=$WAITED_S
  OUTCOME=cleared
else
  CLEAR_S=none
  OUTCOME=not-cleared
fi

FILLER_GIB=$(awk -v bytes="$FILLER_B" 'BEGIN { printf "%.2f", bytes / 1073741824 }')
DETAIL="used_pct=${USED_PCT_BEFORE}->${USED_PCT_FILLED}->${USED_PCT_AFTER} filler_gib=$FILLER_GIB watch=${WATCH_S}s"

result_row "$SCENARIO" "$STARTED_UTC" "-" "$SHA" "$ALERT" \
  "$PENDING_S" "$FIRING_S" "$RECOVERY_S" "$CLEAR_S" "$OUTCOME" "$DETAIL"

[ "$OUTCOME" = cleared ] || exit 1
