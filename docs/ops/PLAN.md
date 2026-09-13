# Ops plan: run the retrieval API on AWS

**Status:** approved 2026-09-12. Weeks 0 and 1 are built, and the week 1 Terraform was applied on 2026-09-12 with the node off.

**Decisions so far:** approach A in section 3. The cloud runs on the real vault, kept private as section 2 describes. The AWS account exists.

**Where it lives:** this repo. Infrastructure, cluster config, and the vault sync go in `deploy/`, workflows in `.github/workflows/`, and ops docs next to this file in `docs/ops/`. The app itself only gets the small PRs listed in section 5.

The goal is to run the Second Brain retrieval API on AWS the way an operations team would. That means infrastructure as code, Kubernetes, a delivery pipeline that refuses to promote a build whose search quality dropped, dashboards and alerts, and a game day that breaks the system on purpose and times the recovery.

## 1. Scope

In scope are the FastAPI retrieval API over the real vault, the MCP server's search tool that calls it, the nightly indexer, the sync that feeds it, monitoring, delivery, and failure drills.

Out of scope are the Next.js frontend, the Chrome clipper, GPUs, and answer generation. Generation runs through Ollama on a desktop, and the cloud node cannot run that model. Hosted generation behind a flag is phase 2.

## 2. Running the real vault privately

Three facts shape the design.

The API has no authentication. CORS keeps browsers on localhost, but any other client that reaches the port can call every route, including note reads and writes.

The index stores the full text of every chunk, and most chunks are exported AI chat transcripts. Some of those transcripts contain pasted keys and passwords.

This repo is public, so every GitHub Actions log is public too.

The design follows from those facts.

- **Nothing on the internet can reach the node.** The security group has no inbound rules at all. The owner reaches the API and Grafana through SSM Session Manager port forwarding, so the MCP server on the desktop can point at `localhost` through the tunnel. CI reaches the cluster through SSM Run Command with its OIDC role. The Kubernetes API port stays closed, and no kubeconfig leaves the node.
- **A scanner runs before anything leaves the desktop.** `deploy/sync/sync_vault.py` runs after the existing nightly job on the desktop. It takes its file list from the indexer's own scanner in `backend/indexer.py`, so it uploads exactly what the cloud indexer will read. It runs a secret scan over every file and refuses to upload a file with any hit. The patterns cover Anthropic, OpenAI, AWS, GitHub, Slack, and Google keys, private key blocks, and password or API key assignments, and they live in `deploy/sync/secret-patterns.txt`. The script prints refused paths to the local console only. A `.cloudignore` file at the vault root, kept out of git, lists anything else the owner wants kept home. The script syncs with `--delete`, so a note deleted or newly refused locally disappears from the cloud copy on the next run.
- **The vault bucket is locked down.** Block Public Access is on, encryption is on, a bucket policy refuses non-TLS requests, only the node's instance role can read it, and only the sync uploader can write to it. The node's EBS volume, which holds the index, is encrypted.
- **Logs never contain vault content.** The eval gate runs as a Kubernetes Job inside the cluster, not on a GitHub runner. It reads the private `dataset.jsonl` from the bucket and prints a summary with numbers only. Before printing, it runs `private_keys_found` from `backend/eval/scorecard.py` over the summary and fails closed on any hit. The smoke test checks status codes and result counts, never titles or snippets. No workflow step prints a question, a note path, or a chunk.
- **The cloud copy stays read-only.** Pods run with a new `READ_ONLY=1` flag that makes every write route return 403. The desktop vault is the only place notes get written, and the nightly sync overwrites the cloud copy anyway.
- **NetworkPolicies limit who reaches the API inside the cluster.** Only pods in the same namespace and Prometheus can call it.

The sync uploader is the one long-lived credential in the design. It is an IAM user whose only permissions are list, put, and delete on the vault bucket. Terraform creates the user and its policy, but the owner creates the access key by hand so the key never lands in Terraform state. Rotate it every 90 days.

## 3. Approaches considered

**A. An ops layer on this app.** Chosen. Terraform, k3s on one EC2 node, GHCR images, eval-gated delivery, Prometheus and Grafana, and a game day. The eval gate and the game day are the parts other ops projects lack. Game-day scenario 3 replays a real incident from this repo, the stale Chroma view after the nightly indexer writes from another process, fixed in PR #25.

**B. A generic home lab.** kind or k3s on a desktop, ArgoCD, Prometheus. Useful practice, but common, there is no cloud, and the dev machine has no Docker yet.

**C. A serverless AWS port.** Bedrock, Lambda, S3, DynamoDB. Strong on AWS services and weak on infrastructure as code, Kubernetes, and monitoring. It reads as an AI app rather than operations work. Its Bedrock piece becomes phase 2 of A.

## 4. What it does

- One command builds the environment in AWS from code, and one command tears it down. Running either twice changes nothing.
- Every night the desktop scans the vault and syncs it to S3, and a CronJob on the node reindexes from that copy.
- Every merge to main that touches `backend/` or the deployed parts of `deploy/` publishes the image and deploys it to staging.
- The gate scores staging against the private eval set. If hit rate falls past the drift rule this repo already uses, promotion stops and the pipeline opens an issue with the numbers. Otherwise prod gets the same image and a smoke test, and a failed smoke rolls prod back.
- Dashboards show request rate, latency, errors, index age, and search quality over time. Alerts fire on slow or failing requests, a late nightly index, or a filling disk.
- A game-day script breaks the system four ways, and each run records time to alert and time to recovery.

## 5. What exists and what changes

Already in the repo:

- `/api/health` and `/api/ready` in `backend/main.py`. They become the liveness and readiness probes.
- `backend/eval/`. `run_eval.py` scores retrieval in process against a local Chroma store and treats a case as ungradable when its expected notes are missing from the index. `scoring.py` has `score_case(retrieved_sources, expected_sources, k)`. `scorecard.py` has `drift_verdict`, which flags a hit-rate drop of 5 points or more, and `private_keys_found`, which catches private fields in a JSON structure.
- `backend/Dockerfile` and the `docker-build` CI job, which builds the image, import-tests it, and asserts CPU-only torch. Nothing pushes the image anywhere.
- `backend/mcp_server.py`, which calls the API over HTTP at `SECOND_BRAIN_API_URL`.
- `.dockerignore`, which keeps `chroma_db`, `dataset.jsonl`, `results.json`, and docs out of the build context. The Dockerfile copies backend files by name, so nothing in `deploy/` can reach the image, and the image published to GHCR holds no vault data.

App changes, one small PR each:

1. A `READ_ONLY` flag. When set, every write route returns 403, with a test per route.
2. A `/metrics` endpoint through `prometheus-fastapi-instrumentator`, plus gauges for retrieval latency, reranker latency, collection count, and time since the index last changed. The last one reuses the write stamp that PR #25 already checks before each query. No metric label carries a query, a title, or a path.
3. JSON logs behind a `LOG_FORMAT=json` switch, with query text left out of the log lines.
4. An HTTP mode for the eval that scores a running service through `GET /api/search` with the existing `score_case`, and prints a numbers-only summary checked by `private_keys_found`. `/api/search` dedupes by title and returns only the served top k, so HTTP scores get their own `deploy/eval/cloud-scorecard.json` and never get compared with the in-process scorecard. Cases whose expected notes the sync refused count as ungradable.
5. Copy `backend/scripts/rebuild_rag_index.py` and `backend/eval/*.py` into the image, so the indexer CronJob and the gate Job run from the same image as the API. `.dockerignore` already keeps the private dataset out.
6. A `publish` job in `ci.yml`. It runs on main only, after `docker-build` passes, and pushes that same amd64 image to GHCR tagged with the commit SHA. The same PR adds `deploy/` to `.dockerignore` to keep the build context small.

## 6. Design

### 6.1 Layout

```
second-brain-tools/
  backend/                    the app, plus the PRs in section 5
  deploy/
    README.md                 bring it up, tear it down, open a tunnel
    ops.py                    bootstrap, init, plan, up, down, tunnel
    tests/                    ops.py command construction
    terraform/
      versions.tf  variables.tf  main.tf  ec2.tf  iam.tf  ssm.tf  s3.tf
      dynamodb.tf  budget.tf  sns.tf  outputs.tf
      backend.tf              S3 state with S3-native locking
      cloud-init.yaml         installs a pinned k3s, single node
      bootstrap/              creates the state bucket, with local state
    k8s/
      base/                   deployment, service, networkpolicy, pvc, cronjob, gate job, configmap
      overlays/staging/
      overlays/prod/
    monitoring/
      prometheus-values.yaml  grafana-values.yaml  alerts.yaml
      dashboards/*.json
    sync/
      sync_vault.py           scan, filter, and upload the vault from the desktop
      secret-patterns.txt     what makes a file too sensitive to upload
      tests/                  fake vaults with planted fake keys
    eval/
      cloud-scorecard.json    numbers only, what the gate compares against
    gameday/
      01-kill-pod.sh  02-fill-disk.sh  03-stale-index.sh  04-bad-config.sh
      results.tsv
    runbooks/                 one per game-day scenario
  docs/ops/
    PLAN.md                   this file
    architecture.md  cost.md  postmortem-stale-index.md
  .github/workflows/
    ci.yml                    existing, gains the publish job
    terraform.yml             checks and plans PRs, applies on main
    deploy.yml                runs after CI succeeds on main, or by hand
    nightly-cost.yml
```

Path filters keep the ops workflows quiet on frontend and docs changes. `terraform.yml` runs only when `deploy/terraform/` or the workflow itself changes. `ops.py` replaced the planned Makefile, because the desktop's make runs recipes through cmd or sh depending on PATH, which breaks quoting for terraform and aws commands. `deploy.yml` runs only when the merged commit touched `backend/`, `deploy/k8s/`, or `deploy/eval/`.

### 6.2 AWS, in Terraform

- Region us-west-2. A 15-dollar monthly cost budget already exists, created by hand before anything else, and Terraform imports it.
- One `m7i-flex.large` EC2 node, with 2 vCPUs and 8 GB of RAM on x86. It is Free Tier eligible for accounts created after July 15, 2025, and 8 GB fits two API pods plus Prometheus and Grafana. It has a 30 GB encrypted root volume and no public inbound ports. `python deploy/ops.py down` destroys it between work sessions, so Free plan credits should cover the whole project. `docs/ops/cost.md` records the real bill.
- The node needs outbound internet for GHCR, S3, and SSM. It gets a public IP with no inbound rules, which costs less than a NAT gateway.
- IAM has an instance role that can read the vault bucket and the SSM parameters and write deploy items. CI assumes GitHub OIDC roles. The repo is public, so the apply role trusts only this repo's `main` branch, plans on pull requests use a read-only role, and pull requests from forks get no OIDC token at all. The deploy role for SSM Run Command arrives in week 4. It trusts the `staging` and `prod` environments, and GitHub creates an environment with no branch limits the first time any job names it, so both environments get restricted to `main` before the role exists. The sync uploader is the IAM user described in section 2.
- SSM Parameter Store holds the Grafana admin password as a SecureString. In phase 2 it also holds the hosted-LLM key.
- SNS holds the alert topic, with an email subscription.
- S3 holds the versioned state bucket, which `deploy/terraform/bootstrap/` creates from its own local state, and the private vault bucket from section 2. State locking uses S3's own lock file, `use_lockfile = true`, because Terraform deprecated DynamoDB state locking in 1.11. Terraform state holds no vault content and no access keys.
- DynamoDB holds a `deploys` table with one item per deploy: SHA, hit rate, p95 latency, and outcome. An `ops.py deploys` subcommand, added in week 4, prints it as TSV. The pipeline writes deploy history there so main never gets bot commits.
- cloud-init installs a pinned k3s, and the Ubuntu AMI already runs the SSM agent. Nobody changes the node by hand.

### 6.3 Kubernetes

- Namespaces `staging` and `prod` share the node, and prod gets the resource guarantees.
- Each namespace runs one API replica, with readiness on `/api/ready`, liveness on `/api/health`, and requests and limits set from measured usage.
- Pod env sets `READ_ONLY=1` and points `OBSIDIAN_VAULT_PATH` and `CHROMA_DB_PATH` into the volume. Set `CHROMA_DB_PATH` explicitly. With a wrong path the backend quietly creates an empty index beside `main.py` and serves empty results with no error.
- A k3s local-path PersistentVolumeClaim holds the index and the synced vault.
- A CronJob runs the nightly indexer in its own pod after the desktop sync window. It pulls the vault from S3 into the volume and runs `rebuild_rag_index.py` while the API keeps serving. That second writer is the condition behind PR #25, and the design keeps it on purpose.
- A gate Job template runs the HTTP eval against the namespace's API service. The pipeline creates it per deploy.
- NetworkPolicies allow traffic to the API only from pods in the same namespace and from Prometheus. k3s enforces them out of the box.
- There is no Ingress. Access goes through the SSM tunnel.
- Kustomize base plus overlays, and the pipeline sets the image tag to the commit SHA.

### 6.4 Pipeline

`deploy.yml` runs when CI, including the publish job, succeeds on main. It also has a `workflow_dispatch` trigger that takes a ref, which game-day scenario 4 uses. Every cluster step goes through SSM Run Command. The node checks out the commit from GitHub, which needs no credentials because the repo is public, and runs `kubectl` locally.

1. Set the staging overlay to the SHA, apply, and wait for ready.
2. Gate. Run the gate Job in staging, read its numbers-only summary, and compare with `cloud-scorecard.json` using `drift_verdict`. A drop of 5 points or more stops the run and opens an issue with the two hit rates.
3. Promote. Set the prod overlay to the SHA, roll out, and wait for ready.
4. Smoke. From inside the cluster, run five fixed queries against prod's `/api/search` and check for a 200 with results, run one `search_vault` call through `mcp_server.py`, and send one write request that must return 403. The output is pass or fail per check. Any failure runs `kubectl rollout undo` and opens an issue.
5. Write the deploy item to DynamoDB.

A PR that changes retrieval on purpose re-records the card against staging with an `ops.py record-cloud-scorecard` subcommand, added in week 4, and commits the new file, which holds numbers only.

`terraform.yml` runs fmt, validate, tflint, and checkov on pull requests and posts the plan as a comment. On main it applies, with the node on or off according to the `OPS_STATE` repo variable.

`nightly-cost.yml` checks whether the node exists and whether the repo variable `OPS_STATE` says it should be `up` or `down`. It alerts when they disagree, so a forgotten node does not burn credits for a month.

### 6.5 Monitoring

- Prometheus and Grafana install through Helm into a `monitoring` namespace. The full kube-prometheus-stack is heavier than this needs.
- App metrics come from the instrumentator and the gauges in section 5. A canary Job runs ten eval-set queries every 15 minutes and records hit rate as a single number.
- node-exporter covers CPU, memory, and disk.
- Dashboards are committed as JSON and provisioned, so a fresh environment has them on first boot.
- Alerts fire when p95 stays above 1.5 seconds for 10 minutes, 5xx responses pass 2 percent, readiness fails, the index is older than 26 hours, disk passes 80 percent, or canary hit rate trips the drift rule. Alertmanager sends them to email through SNS. Alert text carries metric names and values, never vault content.

### 6.6 Game day

Four scripted scenarios, each run three times and timed.

1. Kill the prod pod. Expect a readiness alert, a restart by Kubernetes, and recovery in under a minute.
2. Fill the volume to 95 percent. Expect a disk alert and a clean failure from the indexer CronJob. The runbook covers growing the volume.
3. Run the indexer while the API serves. Expect the index-age gauge to move, PR #25's reopen to pick up the new index, and canary hit rate to stay flat. This is the real incident, replayed.
4. Run `deploy.yml` by hand on a branch whose config breaks retrieval, for example a top k of 1. Expect the gate to block promotion. Then push the same image to prod by hand, expect the canary alert, and roll back by the runbook.

`deploy/gameday/results.tsv` records time to alert and time to recovery for every run. Each scenario gets a runbook, and scenario 3 gets a postmortem with a timeline, impact, root cause, and what changed.

## 7. Prerequisites

These need the repo owner, not an agent.

- Done 2026-09-12: the AWS account on the Free plan, a 15-dollar monthly cost budget that counts usage before credits, the AWS CLI, the Session Manager plugin, Terraform, and Docker Desktop.
- Stay on the Free plan unless the project runs past its six months or its credits. The Free plan closes the account at either limit unless it is upgraded to the Paid plan first.
- Done 2026-09-12: the dry run of `sync_vault.py` on the real vault, which kept 2 of 718 files home, and the first Terraform apply from the desktop. The repo variables `AWS_ACCOUNT_ID`, `TF_STATE_BUCKET`, and `OPS_STATE` and the secret `ALERT_EMAIL` are set.
- Confirm the SNS subscription email. Nothing gets delivered until someone clicks the link.
- The sync uploader's access key, created by hand in the console now that Terraform has created the user.

## 8. Milestones

Weeks rather than dates, because this shares a calendar with other work.

| Week | Output |
|---|---|
| 0, two days | Done. Prerequisites. Architecture doc with a diagram. `sync_vault.py` and its secret patterns, tested on fake vaults with planted fake keys, then a dry run on the real vault with the refused-file list reviewed on the desktop |
| 1 | Done, applied 2026-09-12. Terraform for the node, IAM, OIDC roles, SSM, the S3 buckets, the deploys table, the SNS alert topic, and an import of the existing budget. `ops.py up` and `ops.py down` are idempotent, and `ops.py tunnel` opens the port forward. `terraform.yml` with tflint and checkov |
| 2 | App PRs 1 through 6. Kustomize base and overlays, probes, NetworkPolicies, PVC, CronJob. Staging answers queries through the tunnel. Memory use measured |
| 3 | Prometheus, Grafana, dashboards as JSON, alert rules, notifications, canary |
| 4 | `deploy.yml` end to end with gate Job, promote, smoke, rollback, and deploy records. A check that fails the workflow if any log line matches a note path. `nightly-cost.yml` |
| 5 | Game day, runbooks, postmortem, and `docs/ops/cost.md` from the actual bill |
| 6, three days | `deploy/README.md` and the final architecture doc. Destroy the environment and rebuild it with `python deploy/ops.py up` to prove it works |

Phase 2 starts only after week 6. It adds Bedrock generation behind a flag with its IAM in Terraform and a fifth game-day scenario that blocks its egress. ArgoCD replaces push deploys, and Loki adds logs, with the same no-vault-content rule.

## 9. Caveats

- One node running k3s is not a highly available cluster. Call it single-node Kubernetes.
- There is no public demo. The live system holds private notes, so it gets shown through screenshots, dashboards, the deploy history, and game-day results.
- The secret scan catches known key formats and obvious assignments. It will miss a password pasted in plain prose. `.cloudignore` covers anything the owner knows about, and the bucket and node stay closed to the internet either way.
- The cloud index is the vault minus refused files, so its hit rate can differ slightly from the desktop scorecard. The two cards stay separate.
- The gate protects retrieval quality. Answer quality is not gated.
- Credits run out. The bill stays at zero only if the node gets destroyed when idle and the project fits inside the Free plan window.
