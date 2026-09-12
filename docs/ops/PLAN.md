# Ops plan: run the retrieval API on AWS

**Status:** draft, not started, 2026-09-12.

**Where it lives:** this repo. Infrastructure and cluster config go in `deploy/`, workflows in `.github/workflows/`, and ops docs next to this file in `docs/ops/`. The app itself only gets the small PRs listed in section 5.

The goal is to run the Second Brain retrieval API on AWS the way an operations team would. That means infrastructure as code, Kubernetes, a delivery pipeline that refuses to promote a build whose search quality dropped, dashboards and alerts, and a game day that breaks the system on purpose and times the recovery.

## 1. Scope

In scope are the FastAPI retrieval API, the MCP server's search tool that calls it, the nightly indexer, monitoring, delivery, and failure drills.

Out of scope are the Next.js frontend, the Chrome clipper, GPUs, and answer generation. Generation runs through Ollama on a desktop, and a 4 GB cloud node cannot run that model. Hosted generation behind a flag is phase 2.

## 2. The private vault stays home

Two facts in the code decide the data design.

The API has no authentication. CORS keeps browsers on localhost, but any other client can call every route, and the routes include note reads and writes: `GET` and `POST /api/note/{ref}`, `/api/note/create`, `/api/cowrite`, `/api/clip`, and `/api/index`.

The index stores the full text of every chunk, and most chunks are exported AI chat transcripts. `.dockerignore` keeps the index out of images for that reason, and `backend/eval/scorecard.py` is built on the rule that the dataset and the vault never leave the machine.

So the cloud deployment never sees the real vault.

- It indexes a public demo vault committed at `deploy/demo-vault/`. That is 100 to 200 markdown notes that are safe to publish, such as project write-ups, design docs, or a CC-licensed note set, with real wikilinks so the graph and the keyword leg have something to work with.
- The gate scores it against a public demo eval set, `deploy/eval/demo-dataset.jsonl`, with about 40 cases in the format of `backend/eval/dataset.example.jsonl`. The set is public, so CI runs the gate with no secrets.
- The pods run with a new `READ_ONLY=1` flag that makes every write route return 403.
- The real vault, `dataset.jsonl`, and the committed `scorecard.json` keep working locally exactly as they do now.

The alternative is deploying the real index behind auth. It puts the vault in S3 and the private questions in SSM, and it needs auth in front of every route. One wrong ingress rule would publish the chat transcripts. I recommend the demo vault.

## 3. Approaches considered

**A. An ops layer on this app.** Recommended. Terraform, k3s on one EC2 node, GHCR images, eval-gated delivery, Prometheus and Grafana, and a game day. The eval gate and the game day are the parts other ops projects lack. Game-day scenario 3 replays a real incident from this repo, the stale Chroma view after the nightly indexer writes from another process, fixed in PR #25.

**B. A generic home lab.** kind or k3s on a desktop, ArgoCD, Prometheus. Useful practice, but common, there is no cloud, and the dev machine has no Docker yet.

**C. A serverless AWS port.** Bedrock, Lambda, S3, DynamoDB. Strong on AWS services and weak on infrastructure as code, Kubernetes, and monitoring. It reads as an AI app rather than operations work. Its Bedrock piece becomes phase 2 of A.

## 4. What it does

- One command builds the environment in AWS from code, and one command tears it down. Running either twice changes nothing.
- Every merge to main that touches `backend/` or the deployed parts of `deploy/` builds the image, scans it, and deploys it to staging.
- The pipeline scores staging against the demo eval set. If hit rate falls past the drift rule this repo already uses, promotion stops and the pipeline opens an issue with the numbers. Otherwise prod gets the same image and a smoke test, and a failed smoke rolls prod back.
- Dashboards show request rate, latency, errors, index age, and search quality over time. Alerts fire on slow or failing requests, a late nightly index, or a filling disk.
- A game-day script breaks the system four ways, and each run records time to alert and time to recovery.

## 5. What exists and what changes

Already in the repo:

- `/api/health` and `/api/ready` in `backend/main.py`. They become the liveness and readiness probes.
- `backend/eval/`. `run_eval.py` scores retrieval in process against a local Chroma store. `scoring.py` has `score_case(retrieved_sources, expected_sources, k)`. `scorecard.py` has `drift_verdict`, which flags a hit-rate drop of 5 points or more.
- `backend/Dockerfile` and the `docker-build` CI job, which builds the image, import-tests it, and asserts CPU-only torch. Nothing pushes the image anywhere.
- `backend/mcp_server.py`, which calls the API over HTTP at `SECOND_BRAIN_API_URL`. The smoke test can point it at prod.
- `.dockerignore`, which already keeps `chroma_db`, the private dataset, and docs out of the build context. The Dockerfile copies backend files by name, so nothing in `deploy/` can reach the image.

App changes, one small PR each:

1. A `READ_ONLY` flag. When set, every write route returns 403, with a test per route.
2. A `/metrics` endpoint through `prometheus-fastapi-instrumentator`, plus gauges for retrieval latency, reranker latency, collection count, and time since the index last changed. The last one reuses the write stamp that PR #25 already checks before each query.
3. JSON logs behind a `LOG_FORMAT=json` switch.
4. An HTTP mode for the eval that scores through `GET /api/search` with the existing `score_case`. The gate then tests the deployed service instead of a local store. `/api/search` dedupes by title and returns only the served top k, so HTTP scores get their own `deploy/eval/demo-scorecard.json` and never get compared with the in-process scorecard.
5. One more `COPY` line so `backend/scripts/rebuild_rag_index.py` ships in the image and the indexer CronJob can run it.
6. A `publish` job in `ci.yml`. It runs on main only, after `docker-build` passes, builds for arm64 on a native arm64 runner, and pushes to GHCR tagged with the commit SHA. Emulating arm64 on an x86 runner would make the Rust and pip stages painfully slow. The same PR adds `deploy/` to `.dockerignore` to keep the build context small.

## 6. Design

### 6.1 Layout

```
second-brain-tools/
  backend/                    the app, plus the PRs in section 5
  deploy/
    README.md                 bring it up, tear it down
    Makefile                  up, down, plan, deploy-staging, promote, gameday, deploys
    terraform/
      main.tf  ec2.tf  iam.tf  ssm.tf  s3.tf  dynamodb.tf  outputs.tf
      backend.tf              S3 state with S3-native locking
      cloud-init.yaml         installs k3s, single node
    k8s/
      base/                   deployment, service, ingress, middlewares, pvc, cronjob, configmap
      overlays/staging/
      overlays/prod/
    monitoring/
      prometheus-values.yaml  grafana-values.yaml  alerts.yaml
      dashboards/*.json
    demo-vault/               the public notes the cloud indexes
    eval/
      demo-dataset.jsonl      public eval cases
      demo-scorecard.json     the recorded HTTP hit rate the gate compares against
    gameday/
      01-kill-pod.sh  02-fill-disk.sh  03-stale-index.sh  04-bad-config.sh
      results.tsv
    runbooks/                 one per game-day scenario
  docs/ops/
    PLAN.md                   this file
    architecture.md  cost.md  postmortem-stale-index.md
  .github/workflows/
    ci.yml                    existing, gains the publish job
    terraform.yml             runs only for deploy/terraform/**
    deploy.yml                runs after CI succeeds on main, or by hand
    nightly-cost.yml
```

Path filters keep the ops workflows quiet on frontend and docs changes. `terraform.yml` runs only when `deploy/terraform/` changes. `deploy.yml` runs only when the merged commit touched `backend/`, `deploy/k8s/`, `deploy/demo-vault/`, or `deploy/eval/`.

### 6.2 AWS, in Terraform

- Region us-west-2. A 20-dollar monthly budget alarm is the first resource created.
- One `t4g.medium` EC2 node with 4 GB of RAM on ARM, an Elastic IP, and a 30 GB root volume. On demand that is about 25 dollars a month. `make down` destroys it between work sessions, which should keep the whole project between 10 and 30 dollars.
- The security group opens 80 and 443 only. Port 80 exists for the Let's Encrypt challenge and the HTTPS redirect. There is no port 22, and shell access goes through SSM Session Manager.
- IAM has an instance role that can read the demo-vault bucket and the SSM parameters. CI assumes GitHub OIDC roles for Terraform and `kubectl`, and nothing uses long-lived access keys. The repo is public, so the apply role's trust policy accepts only this repo's `main` branch and the `staging` and `prod` environments. Plans on pull requests use a separate read-only role, and pull requests from forks get no OIDC token at all.
- SSM Parameter Store holds the Grafana admin password and the alert webhook as SecureStrings. In phase 2 it also holds the hosted-LLM key.
- S3 holds a versioned state bucket and a demo-vault bucket that `deploy.yml` syncs from `deploy/demo-vault/`. State locking uses S3's own lock file, `use_lockfile = true`, because Terraform deprecated DynamoDB state locking in 1.11.
- DynamoDB holds a `deploys` table with one item per deploy: SHA, hit rate, p95 latency, and outcome. `make deploys` prints it as TSV. The pipeline writes deploy history there so main never gets bot commits.
- cloud-init installs k3s. Nobody changes the node by hand.

### 6.3 Kubernetes

- Namespaces `staging` and `prod` share the node, and prod gets the resource guarantees.
- Each namespace runs one API replica, with readiness on `/api/ready`, liveness on `/api/health`, and requests and limits set from measured usage.
- Pod env sets `READ_ONLY=1` and points `OBSIDIAN_VAULT_PATH` and `CHROMA_DB_PATH` into the volume. Set `CHROMA_DB_PATH` explicitly. With a wrong path the backend quietly creates an empty index beside `main.py` and serves empty results with no error.
- A k3s local-path PersistentVolumeClaim holds the index and the synced demo vault.
- A CronJob runs the nightly indexer in its own pod. It syncs the demo vault from S3 into the volume and runs `rebuild_rag_index.py` while the API keeps serving. That second writer is the condition behind PR #25, and the design keeps it on purpose.
- Ingress goes through Traefik, which ships with k3s. cert-manager gets a Let's Encrypt certificate for an `sslip.io` hostname, so there is no domain to buy. Traefik middlewares put a rate limit on the API and basic auth on Grafana.
- Kustomize base plus overlays, and the pipeline sets the image tag to the commit SHA.

### 6.4 Pipeline

`deploy.yml` runs when CI, including the publish job, succeeds on main. It also has a `workflow_dispatch` trigger that takes a ref, which game-day scenario 4 uses.

1. Sync `deploy/demo-vault/` to S3 if it changed.
2. Set the staging overlay to the SHA, apply, and wait for ready. If the demo vault changed, run the indexer job first.
3. Gate. Score staging through the HTTP eval mode against `deploy/eval/demo-dataset.jsonl` and compare with `demo-scorecard.json` using `drift_verdict`. A drop of 5 points or more stops the run and opens an issue with both numbers.
4. Promote. Set the prod overlay to the SHA, reindex if the vault changed, roll out, and wait for ready.
5. Smoke. Run five known queries against prod's `/api/search`, one `search_vault` call through `mcp_server.py` with `SECOND_BRAIN_API_URL` set to prod, and one write request that must return 403. Any failure runs `kubectl rollout undo` and opens an issue.
6. Write the deploy item to DynamoDB.

A PR that changes retrieval on purpose, or changes the demo set, re-records the card with `make record-demo-scorecard` against staging and commits the new file.

`terraform.yml` runs fmt, validate, tflint, and checkov on pull requests and posts the plan as a comment. On main it applies.

`nightly-cost.yml` checks whether the node exists and whether the repo variable `OPS_STATE` says it should be `up` or `down`. It alerts when they disagree, so a forgotten node does not bill for a month.

### 6.5 Monitoring

- Prometheus and Grafana install through Helm, sized for a 4 GB node. The full kube-prometheus-stack is too heavy for it.
- App metrics come from the instrumentator and the gauges in section 5. A canary runs ten demo queries every 15 minutes and records hit rate.
- node-exporter covers CPU, memory, and disk.
- Dashboards are committed as JSON and provisioned, so a fresh environment has them on first boot.
- Alerts fire when p95 stays above 1.5 seconds for 10 minutes, 5xx responses pass 2 percent, readiness fails, the index is older than 26 hours, disk passes 80 percent, or canary hit rate trips the drift rule. Alertmanager sends them to Discord or email.

### 6.6 Game day

Four scripted scenarios, each run three times and timed.

1. Kill the prod pod. Expect a readiness alert, a restart by Kubernetes, and recovery in under a minute.
2. Fill the volume to 95 percent. Expect a disk alert and a clean failure from the indexer CronJob. The runbook covers growing the volume.
3. Run the indexer while the API serves. Expect the index-age gauge to move, PR #25's reopen to pick up the new index, and canary hit rate to stay flat. This is the real incident, replayed.
4. Run `deploy.yml` by hand on a branch whose config breaks retrieval, for example a top k of 1. Expect the gate to block promotion. Then push the same image to prod by hand, expect the canary alert, and roll back by the runbook.

`deploy/gameday/results.tsv` records time to alert and time to recovery for every run. Each scenario gets a runbook, and scenario 3 gets a postmortem with a timeline, impact, root cause, and what changed.

## 7. Prerequisites

These need the repo owner, not an agent.

- An AWS account with a card on it, and the budget alarm set before anything else.
- Docker Engine inside the existing WSL2 Ubuntu install. Docker Desktop is not needed.
- A decision on what goes in the demo vault.
- A review of the drafted demo eval cases.
- A Discord webhook or an email address for alerts.

## 8. Milestones

Weeks rather than dates, because this shares a calendar with other work.

| Week | Output |
|---|---|
| 0, two days | Prerequisites. Architecture doc with a diagram. Demo vault and demo eval set drafted and reviewed |
| 1 | Terraform for the node, IAM, OIDC roles, SSM, S3 state, and the deploys table. `make up` and `make down` are idempotent. `terraform.yml` with tflint and checkov |
| 2 | App PRs 1 through 6. Kustomize base and overlays, probes, PVC, CronJob, ingress with TLS and middlewares. Staging answers demo queries. Memory use measured |
| 3 | Prometheus, Grafana, dashboards as JSON, alert rules, notifications, canary |
| 4 | `deploy.yml` end to end with gate, promote, smoke, rollback, and deploy records. `nightly-cost.yml` |
| 5 | Game day, runbooks, postmortem, and `docs/ops/cost.md` from the actual bill |
| 6, three days | `deploy/README.md` and the final architecture doc. Destroy the environment and rebuild it from `make up` to prove it works |

Phase 2 starts only after week 6. It adds Bedrock generation behind a flag with its IAM in Terraform and a fifth game-day scenario that blocks its egress. ArgoCD replaces push deploys, and Loki adds logs.

## 9. Caveats

- One node running k3s is not a highly available cluster. Call it single-node Kubernetes.
- Two API pods, Prometheus, Grafana, and k3s in 4 GB is tight. If week 2's measurements say it does not fit, scale staging to zero between deploys or move to a `t4g.large` at about twice the hourly cost.
- Every number the cloud publishes describes the demo vault. The real vault's scorecard stays local, as it does today.
- The gate protects retrieval quality. Answer quality is not gated.
- It costs real money. The bill stays small only if the node gets destroyed when idle.

## 10. Open decisions

- Approach A, or C.
- An AWS account. Without one this turns into approach B.
- Demo vault or the real vault behind auth. Section 2 recommends the demo vault.
- What goes in the demo vault.
