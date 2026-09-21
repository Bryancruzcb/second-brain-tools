# Runbooks

One runbook per game-day scenario (`docs/ops/PLAN.md`, section 6.6). Each one
is written for whoever is holding the pager, not for whoever built the system.

    api-not-ready.md      the API pod is gone, or will not become Ready
    disk-almost-full.md   the node's root disk is filling, and growing it
    stale-index.md        the index looks old, or search gets worse mid-build
    bad-deploy.md         the gate blocked a promotion, or a bad image is in prod

The game day has not been run yet, so none of these quote a measured time to
alert or time to recovery. `deploy/gameday/results.tsv` is where those go.

## When to reach for one

Alerts arrive as GitHub issues on this repository. Alertmanager posts each
group to `deploy/monitoring/alert_bridge.py`, which opens an issue titled
`Alert: <name> in <namespace>` with the `alert` label, comments when the alert
repeats, and comments and closes it when the alert resolves. Rules that do not
aggregate by namespace (`DiskAlmostFull`, `CanaryNotRunning`,
`CanaryNeverReported`) open `Alert: <name>` with no namespace.

Start at the alert name and open the runbook that lists it. A failed deploy is
a different issue: `Deploy failed: <first 7 of the SHA>`, label
`deploy-failure`, opened by `.github/workflows/deploy.yml`.

If something is clearly wrong and no issue appeared, check that the bridge has
its token. Without `/second-brain-ops/github-alerts-token` in SSM the bridge
runs and only logs what it would have posted (`deploy/monitoring/README.md`).

## The two ways to touch the system

Nothing on the internet reaches the node. The security group has no inbound
rules, there is no Ingress, and the Kubernetes API port is closed. There is no
`kubectl` on the desktop that talks to the cluster. Everything goes one of two
ways.

**A script on the node, over SSM Run Command.** `send_command.py` puts
`/opt/sbt` at a commit and runs one script from that commit as root, waits,
prints what it printed, and exits with its code:

    python deploy/pipeline/send_command.py --sha <40-hex commit> --timeout 1200 \
      --script deploy/pipeline/rollback.sh -- prod

`--script` is a path inside the checkout, so only scripts that exist in the
repo can run: `status.sh` (read-only, and the first one to reach for),
`reindex.sh`, `deploy-namespace.sh`, `run-job.sh` and `rollback.sh`
(`deploy/pipeline/README.md`). Exit 5 means the output was refused before it
was printed, because a public workflow log cannot be taken back; the output is
still in the SSM invocation, which is not public.

**A tunnel from this desktop.** SSM port forwarding to a pinned service
address:

    python deploy/ops.py tunnel                          # staging on localhost:8000
    python deploy/ops.py tunnel --to prod --local-port 8001
    python deploy/ops.py tunnel --to grafana             # http://localhost:3000

The tunnel needs the node running; with it off, `ops.py` says so and exits.
Grafana's user is `admin` and its password comes from SSM, with the command in
`deploy/monitoring/README.md`. A pod that is not Ready has no Service
endpoints, so a tunnel to an unready namespace connects and then reaches
nothing.

Two reads need neither: `python deploy/ops.py deploys` prints the deploy
history from DynamoDB, which survives `ops.py down`, and the GitHub Actions
run linked from a deploy-failure issue holds the failing step's own output.
