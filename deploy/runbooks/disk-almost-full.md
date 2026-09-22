# The node's disk is almost full

Game-day scenario 2. Read `README.md` in this folder first if you do not know
how to reach the node.

## What you will see

An issue titled `Alert: DiskAlmostFull`, label `alert`, severity critical, and
no namespace in the title: the rule aggregates over the whole node, so there
is no namespace label to put there
(`deploy/monitoring/rules/second-brain.yml`). It fires when the root disk is
above 80 percent for 10 minutes.

In Grafana, "Root disk used" on the "Second Brain API" dashboard is above 0.8.
If a build was running when the disk filled, `Alert: IndexerStale in
<namespace>` follows later, because the failed run never recorded a success.

## What it means

There is one disk. The node has a single 30 GB encrypted gp3 root volume
(`deploy/terraform/ec2.tf`), and everything sits on it: both namespaces'
volumes, each holding the synced vault copy, the Chroma index and the model
cache; Prometheus's data, kept 7 days and capped at 1500MB on a 4Gi volume
(`deploy/monitoring/prometheus.yaml`); and the container images. The PVC asks
for 5Gi, but k3s's local-path provisioner backs it with a directory on that
same root volume, so the request is not a quota
(`deploy/k8s/base/pvc.yaml`). One namespace can fill the disk for everything
else.

**The kubelet acts on this disk too, and faster than you will.** Read from
the node's kubelet config on 2026-09-22 (k3s defaults):

| used | what happens |
|---|---|
| 80% | this alert goes pending, and fires after 10 minutes |
| 85% | the kubelet deletes unused container images until the disk is back at 80% |
| 95% | free space is under 5%, and the kubelet evicts pods and taints the node `NoSchedule` |

So the alert is five points of warning before the kubelet starts quietly
deleting images, which can pull the disk back under 80 percent and make the
alert clear while whatever is growing keeps growing. It is fifteen points
before evictions. At 95 percent the kubelet evicted both API pods and Grafana
within 20 seconds during the first game day, and the node kept its taint for
five minutes after the space came back (`evictionPressureTransitionPeriod`),
so nothing could reschedule in that time either. If you see `ApiNotReady` in
both namespaces at once, check the disk before anything else.

What is not broken, below that eviction line: the API keeps serving reads from the index it already has,
and a full disk stops the indexer rather than corrupting anything — the
CronJob has `backoffLimit: 0`, so a failed run waits for tomorrow instead of
retrying into the same wall. Nothing on this disk is the only copy of
anything. The vault is on the desktop and in S3, Terraform state is in S3, and
the deploy history is in DynamoDB.

## Check

1. The dashboard, for how fast and how full:

        python deploy/ops.py tunnel --to grafana     # then http://localhost:3000

   "Root disk used" for the slope, "Node CPU busy" and "Chunks in the index"
   for whether an index build is running right now, and "Since the last
   successful index run" for whether one already failed.

2. Whether a deploy is in flight:

        python deploy/ops.py deploys

3. The node itself, read-only:

        python deploy/pipeline/send_command.py --sha <40-hex commit> --timeout 300           --script deploy/pipeline/status.sh -- prod

   Its last line is `df` on `/`, which is the filesystem `DiskAlmostFull`
   watches, and the Jobs above it say whether an index build is running or
   already failed. Run it for `staging` too: both namespaces share the one
   disk, so the namespace that filled it is not always the one that alerted.

   What it does not answer is which directory grew. There is no shell on the
   node from the desktop, and `status.sh` prints fixed fields on purpose. See
   the last section.

## Fix

**Grow the volume.** The size is written in `deploy/terraform/ec2.tf`, in the
instance's `root_block_device` (`volume_size = 30`). Raise it, read the plan,
then apply:

    python deploy/ops.py plan --up
    python deploy/ops.py up

Read the plan before applying, and say what you are agreeing to. An EBS volume
can be grown and never shrunk, so the larger size is billed from now until the
node is destroyed, against a 15-dollar monthly budget
(`docs/ops/PLAN.md`, section 6.2). And if the plan shows the instance being
replaced rather than changed in place, that is not a resize, it is a new node:
the index goes with the old root disk and has to be rebuilt.

After the volume grows, the node's filesystem has to pick up the new size
before anything sees the space. "Root disk used" in Grafana is how you tell.
If the volume is bigger and the panel has not moved, treat it as the next case.

**Replace the node.** `python deploy/ops.py down` then `python deploy/ops.py
up` gives a node at the size Terraform now says, with nothing on it. What is
lost: the index lives on the node's root disk, so every `down` takes it, and
the next deploy rebuilds it — 22 minutes for 5,941 chunks on staging's first
build of the 775-file vault (`deploy/k8s/README.md`). The model cache goes
too, so the first pod also re-downloads its weights. The vault copy comes back
from S3 on the next indexer run. Set `OPS_STATE` to match afterwards; `ops.py`
prints the command.

**Do not wait for the indexer to sort itself out.** It will not. A run that
failed on a full disk does not retry, and the next scheduled one is 06:00 UTC
(`deploy/k8s/base/cronjob-indexer.yaml`).

## Verify

"Root disk used" back below 0.8, and the bridge comments on
`Alert: DiskAlmostFull` and closes it when the alert resolves. Then confirm
the indexer recovered: "Since the last successful index run" resets after the
next run, and `Alert: IndexerStale` closes if it had opened. If you replaced
the node, the namespace is only back when "API replicas available" is 1 and
"Chunks in the index" is populated.

## If it keeps happening

- Prometheus is the growth you can bound without touching the app:
  `retention`, `retentionSize` and the volume size in
  `deploy/monitoring/prometheus.yaml`.
- The node volume is the real limit: `deploy/terraform/ec2.tf`. It is a
  literal, not a variable, so a change there is a change to the instance.
- Both namespaces' indexers start at 06:00 UTC and each takes about one of
  the node's two CPUs. `deploy/k8s/README.md`, "Known follow-ups", already
  says prod's schedule should move later if the nightly run grows; the
  schedule is in `deploy/k8s/base/cronjob-indexer.yaml`.
- Raising the PVC request in `deploy/k8s/base/pvc.yaml` changes nothing about
  how much space is available. local-path does not enforce it.
- The gap still open: `status.sh` prints `df` on `/` but no `du` of the two
  volume directories, so it says the disk is filling and not what filled it.
  The reason is what may be printed: a `du` lists directory names, and a
  local-path volume's directories are named after the PVC and the pod, which
  is safe, while anything that walked into the vault copy would not be. If
  this question comes up twice, add a `du` pinned to the two volume roots and
  a fixed depth, so it can name only directories the manifests already name.
