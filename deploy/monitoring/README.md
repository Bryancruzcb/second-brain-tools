# Monitoring

Prometheus, Grafana, alert rules, and a bridge that turns alerts into GitHub
issues, all in the `monitoring` namespace on the one node. Nothing here is
reachable from the internet; the owner reaches Grafana through the SSM tunnel.

    prometheus.yaml      HelmChart: Prometheus, Alertmanager, kube-state-metrics,
                         node-exporter, Pushgateway (prometheus-community 29.31.1)
    grafana.yaml         HelmChart: Grafana with the datasource and dashboards
                         provisioned (grafana-community 13.2.5)
    rules/               alert rules, and their promtool unit tests
    dashboards/          the Grafana dashboard, as JSON
    alert_bridge.py      Alertmanager webhook -> GitHub issues
    alert-bridge.yaml    its Deployment and Service

The canary that feeds the quality alert is a CronJob in each app namespace
(`deploy/k8s/base/cronjob-canary.yaml`, code in `backend/eval/canary.py`).

## Apply

    kubectl apply -k deploy/monitoring

k3s's built-in Helm controller installs the two charts from their
`HelmChart` objects, so the node needs no helm binary. The app namespaces
need nothing extra: the API pods carry `prometheus.io/scrape` annotations,
and their NetworkPolicy already admits the `monitoring` namespace.

## Grafana

    python deploy/ops.py tunnel --to grafana    # then http://localhost:3000

The user is `admin`. The password is the SecureString Terraform created:

    aws ssm get-parameter --name /second-brain-ops/grafana-admin-password --with-decryption --query Parameter.Value --output text

The "Second Brain API" dashboard is provisioned from `dashboards/`: search
latency, status codes, 5xx share, retrieval and rerank time, index size and
age, the last indexer success, the canary against its baseline, pod memory
against limits, and the node's CPU, memory and disk.

## Alerts reach GitHub as issues

Alertmanager groups alerts by name and namespace and posts each group to the
bridge. The bridge opens an issue titled `Alert: <name> in <namespace>` with
the `alert` label, comments when the alert repeats, and comments and closes
the issue when it resolves. The open issue is its only state, so it can
restart without duplicating anything.

The repository is public, so the bridge passes on only the alert name,
namespace, severity, start time and summary, and every summary quotes metric
values only. SNS email was the plan, but its confirmation mail never reached
the owner's inbox (three tries, 2026-09-12 to 09-18), and GitHub mail does.

**The token (Bryan, once).** Create a fine-grained token on GitHub for this
repository only, with **Issues: Read and write**, and store it where the
node can read it, from your own terminal:

    $t = Read-Host -AsSecureString "token"
    aws ssm put-parameter --name /second-brain-ops/github-alerts-token --type SecureString --overwrite --value ([System.Net.NetworkCredential]::new('', $t).Password)

It never goes into git, chat, or a Kubernetes Secret: an init container reads
it with the node's instance role into a memory-only volume. Until it exists,
the bridge runs and only logs what it would have posted. After creating it,
restart the bridge: `kubectl -n monitoring rollout restart deployment/alert-bridge`.

## What alerts, and why at that level

| Alert | Fires when | Why that line |
|---|---|---|
| SearchLatencyHigh | search p95 above 3 s for 10 min | staging measured 1.92 s through the tunnel (2026-09-19); 3 s is about 1.5 times that and a histogram bucket edge |
| ServerErrorsHigh | 5xx above 2% for 10 min, with at least 20 requests | at canary-only traffic one failure is 10%, and the canary alerts cover that |
| ApiNotReady | fewer ready API pods than the Deployment asks for, for 5 min | a fresh node is unready for about 2 min while the first index lands |
| IndexerStale | the indexer CronJob hasn't succeeded for 26 h, or never has since it was created 26 h ago | the API's index-age gauge grows whenever the vault doesn't change, which is normal |
| DiskAlmostFull | root disk above 80% for 10 min | it holds the index, the vault copy and Prometheus's data |
| CanaryHitRateDropped | canary hit rate below its recorded baseline for two runs | ten fixed questions: one miss is ten points, past the gate's five-point drift rule |
| CanaryErrors | the canary couldn't reach the API, two runs in a row | an outage, kept apart from a quality drop |
| CanaryNotRunning / CanaryNeverReported | no canary result for 45 min | the Pushgateway keeps the last push, so a stopped canary shows as an old timestamp |

`rules/second-brain.test.yml` has a firing and a quiet case for each, run
with `promtool test rules` in CI.

## What the first run showed, 2026-09-19

The stack came up on a fresh node in about three minutes: all seven pods
running, every scrape target healthy (the API through its annotations,
kube-state-metrics, node-exporter, the Pushgateway and Prometheus itself),
all nine rules loaded, and Grafana provisioning its datasource and
dashboards with no errors.

The canary ran on schedule. Its first run, 6 minutes into the 22-minute
first index build, scored 0.4 on a partly built index; once the build
finished it scored 10 of 10, which is the card in
`deploy/k8s/base/canary-card.json` (MRR 0.92, recorded from the desktop
through the tunnel).

Alerts reach GitHub. A synthetic alert posted to Alertmanager opened issue
#43 with the `alert` label, carrying only the alert name, namespace,
severity, start time and summary; when it resolved three minutes later the
bridge commented and closed it, 220 seconds after it opened.

**A full index build roughly doubles search latency.** During the build,
search p95 was 4.45 s and p50 2.61 s, with the node 72 percent busy;
afterwards the same queries ran at p95 1.97 s and p50 1.72 s. The node's two
vCPUs are one physical core, so the indexer's embedding work and the API's
reranker share it. `SearchLatencyHigh` went pending during the build and
cleared by itself when the build finished. That is the alert doing its job,
and the first build on a fresh node is its known cause; the nightly run is
incremental and much shorter.

## Memory

Requests in `monitoring`: Prometheus 384 MiB (limit 768), Grafana 128 MiB,
the reload sidecar, Alertmanager, kube-state-metrics, node-exporter,
Pushgateway and the bridge about 170 MiB together, about 0.7 GiB in all. With
the app namespaces at their 06:00 UTC peak (4.4 GiB, `deploy/k8s/README.md`)
that is about 5.1 GiB of the node's 7.6. Prometheus keeps 7 days, capped at
1.5 GB on a 4 GiB volume.

## Code units

- `backend/eval/canary.py`: FP. Sampling the cases, matching the baseline and
  writing the exposition text are calculations over plain data; the HTTP
  calls and the push are thin actions at the edge.
- `deploy/monitoring/alert_bridge.py`: FP. `plan` turns a webhook payload and
  the open issue into immutable actions; the GitHub client and the
  single-threaded webhook server only apply them, one webhook at a time.
