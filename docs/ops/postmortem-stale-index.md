# Postmortem: the backend served a stale index

The incident this repo replays as game-day scenario 3 (`docs/ops/PLAN.md`, section 6.6). It
happened on the desktop before any of the ops work existed.

Times are Pacific. Git commit times are the desktop's local time (UTC-7); GitHub timestamps
are UTC and appear in brackets. Every claim below comes from a commit, a pull request, or a
file in this repo, and anything that was never measured says so.

## Summary

On 2026-09-10 the running backend answered searches from a Chroma view that no longer matched
the store on disk, because the nightly indexer had rewritten that store from its own process.
Scoped Ask requests returned 500, `/api/search` returned an empty list with a 200, and
unscoped Ask answered from the pre-write index. PR #25 made the backend read Chroma's sqlite
write counter before each query, reopen the store when it moved, and retry once when a query
still met a stale view. One person's search results were wrong until the backend was
restarted; nothing on disk was lost or corrupted.

## Timeline

The start is not recorded. Nothing measured when the running process's view first went stale,
and there was no metric or alert that could have.

| When | What | Source |
|---|---|---|
| 2026-07-20 19:54 | `scripts/auto_archive.py` begins running `backend/scripts/rebuild_rag_index.py` in its own process. That second writer is the condition the incident needs; whether any earlier backend served a stale view is not recorded | 25738b6 |
| before 2026-09-10 21:30 | A live check of the backend on the desktop finds `POST /api/query` returning 500 `Error executing plan: Internal error: Error finding id` on `scope=notes` (the UI default) and `scope=chats`, while `scope=all` answers. The time it began is not recorded | PR #24 body |
| 2026-09-10 21:30 [09-11 04:30 UTC] | First attempt: drop the Chroma `where` filter and scope in Python. PR #24 opened, marked do-not-merge until a live smoke | 0e2db03, PR #24 |
| 2026-09-10, evening | Reproduced against a copy of the live index. A reader holds a client the way uvicorn does; a second process deletes 20 chunks and re-adds them. Afterwards `get_collection()` and a second `PersistentClient()` both stay stale, and only close plus reopen recovers | PR #25 body, e31cd0e message |
| 2026-09-10 22:21 [09-11 05:21 UTC] | The reopen fix is committed and PR #25 opened | e31cd0e, PR #25 |
| 2026-09-10 22:24 [09-11 05:24 UTC] | PR #24 closed unmerged, superseded: it removed the error message but kept serving the stale index | PR #24 comment |
| 2026-09-10 22:48 [09-11 05:48 UTC] | An independent review of the first cut finds four concurrency and failure-path problems; all four are fixed with a test each, and the findings are written up on the PR at 05:56 UTC | c9b4bcd, PR #25 comment |
| 2026-09-10 22:57 [09-11 05:57 UTC] | PR #25 merged | 0b925db |

## Impact

One person. This is a personal vault with a single user, and the backend was running on his
desktop, so the blast radius was his own search results for as long as that process stayed up.

What the endpoints did, per PR #24 and PR #25:

- `POST /api/query` with `scope=notes` or `scope=chats` returned 500.
- `/api/search` returned 200 with zero results. The handler catches every exception and
  returns `{"results": []}` (`backend/main.py`), so the same failure was silent there.
- `POST /api/query` with `scope=all` returned 200 from the pre-write index: chunks that had
  been deleted still surfaced, and newly indexed ones were missing.

Not affected: the store on disk. The indexer's writes landed correctly, and only the
long-lived reader's in-memory view was wrong. Restarting the backend restored correct answers,
and the fix needed no reindex. Note writing, the nightly pass itself, and anything that opened
its own process were all fine.

How long it lasted is not recorded. The window opens with the first external write after the
backend last opened the store and closes when that process restarts. The only bound on record
is same-day: PR #25 says a fresh backend that morning did not show it and the live check that
evening did.

## Root cause

`chromadb.PersistentClient` is process-local. The sqlite file is shared, but the HNSW index
lives in the client's memory and is never invalidated by another process's writes. After the
nightly pass rewrote the store, a `where`-filtered query joined fresh sqlite rows against the
stale in-memory index and died with `Error finding id`; an unfiltered query stayed inside the
stale index and answered from it without error. That is the whole mechanism: a reader holding
a view of a store someone else rewrote.

Recovery needed more than asking Chroma again. In the reproduction, `get_collection()` and a
second `PersistentClient()` in the same process both handed back the same stale view, because
chromadb caches one System per path. Only closing the client and clearing that cache worked,
which is what `_close_chroma()` in `backend/main.py` now does.

Two writers are normal here by design, not by accident: a long-lived uvicorn serves while the
nightly pass indexes from its own process. Nothing told the reader its view had expired.

## Why it was not caught sooner

Nothing watched retrieval between deploys. The one loud symptom was a 500 in the UI, and the
rest of the failure was silent.

- There was no metrics endpoint. `/metrics` arrived on 2026-09-16 in 50a9d97 (PR #31), five
  days after the fix.
- There was no Prometheus, no alert rules, no dashboards, and no canary. The stack, the nine
  rules and the dashboard arrived on 2026-09-19 in 49d35c2, the canary in 7c5c556 (both
  PR #41), and its recorded baseline in a9f2d15 (PR #42).
- `/api/search` returned an empty list rather than an error, so the symptom that a quality
  check would have caught looked like a quiet day.
- The eval that did exist, `backend/eval/run_eval.py`, scores retrieval in process against the
  store on disk (PLAN.md section 5). It opens its own fresh view, so it cannot see a stale one
  in another process. The nightly `--check` on the same index that night scored 100 percent
  hit@8 (PR #25 comment), which says nothing about what the running backend was serving.
- `/api/ready` reported which components had loaded, not whether the open collection could
  answer anything.

## What changed

### The fix, PR #25 (e31cd0e and c9b4bcd, merged as 0b925db)

All in `backend/main.py` unless named otherwise.

- `_chroma_write_stamp()` reads Chroma's per-segment high-water mark from the `max_seq_id`
  table in `chroma.sqlite3`, read-only with a 0.5 second timeout. It moves on writes and stays
  put across a plain open, which the file's mtime does not.
- `ensure_chroma_fresh()` runs before each query, compares that stamp with the value recorded
  when this process opened the store, and reopens when it moved. `REOPEN_COOLDOWN_S = 15`
  stops a long external index run from reloading on every request, and a failed open is
  retried by a later call instead of latching the backend dead.
- `reopen_chroma()` closes the client, clears chromadb's per-path system cache, opens the
  store again, and rebuilds BM25. `expected_stamp` and `expected_generation` are compared
  under `_chroma_lock`, so two requests that failed together do not reopen back to back, and a
  reopen is declined while this process is ingesting through `/api/index`.
- `retrieve_for_request()` retries exactly once when a query still dies with a stale-store
  error. `_is_stale_store_error()` counts both the Chroma error and the `AttributeError` about
  `bindings` that a query in flight sees when another thread stopped the client underneath it.
- `POST /api/lexical/refresh` reopens the store and reports `reopened`, and the nightly pass
  calls it when it finishes (`backend/scripts/rebuild_rag_index.py`). In-process ingestion
  advances the stamp instead of reopening, since it already sees its own writes.
- `backend/tests/test_chroma_refresh.py` covers the retry, the proactive check, the cooldown,
  the ingestion flag, and the four review findings, including a regression test that writes
  the store from a subprocess.

PR #25 recorded the cost: a reopen (close, reopen, rebuild BM25 over about 5,300 chunks) took
6 to 12 seconds on the desktop. It happens once after the nightly pass, never per request.

### What the ops work adds

| Piece | Where | What it gives this failure |
|---|---|---|
| Index-age gauge | `second_brain_index_age_seconds` in `backend/metrics.py`, `_index_age_seconds()` in `backend/main.py`, served on `/metrics` (50a9d97) | Seconds since this process last saw the store change on disk, so the indexer's write is visible from the API's own side and on the Grafana dashboard. It keeps its own copy of the stamp (`_index_stamp_metric`) so that reading the gauge cannot tell `ensure_chroma_fresh()` the write was already seen, which would reintroduce this exact bug for the sake of a metric. There is a test for that. |
| Collection gauge | `second_brain_collection_chunks`, same commit | A view serving an empty or shrunken collection shows up as a number instead of as quiet results. |
| IndexerStale | `deploy/monitoring/rules/second-brain.yml` | Fires when the indexer CronJob has not succeeded for 26 hours, or has never succeeded since it was created that long ago. It watches the job rather than the age gauge, because the gauge grows whenever the vault does not change, which is normal here. |
| Canary and CanaryHitRateDropped | `backend/eval/canary.py`, `deploy/k8s/base/cronjob-canary.yaml`, baseline in `deploy/k8s/base/canary-card.json`, rule in `rules/second-brain.yml` | Ten fixed questions through `/api/search` every 15 minutes, scored against a recorded baseline. A stale view returns an empty list there, which the canary grades as a miss, so the silent half of this incident becomes a falling number. One miss moves the rate ten points, and the alert needs two runs below baseline. |
| Readiness on a populated index | `/api/ready?strict=1` in `backend/main.py` (4b6b8b6, PR #38), wired as the readinessProbe in `deploy/k8s/base/deployment.yaml`; `ApiNotReady` in the rules | A pod whose collection holds no chunks stays out of the Service instead of answering every query with nothing and no error, which staging did before its first index build. While the index looks empty the probe also reopens the store itself, because a pod that is not Ready has no Service endpoints for the indexer's refresh call to reach. |
| ServerErrorsHigh | `rules/second-brain.yml` | The scoped-Ask 500s would land in the 5xx share, but the rule needs 20 requests in 10 minutes and one person's traffic may not reach that. The canary alerts cover the low-traffic case (`deploy/monitoring/README.md`). |

The cloud design keeps the second writer on purpose. `deploy/k8s/base/cronjob-indexer.yaml`
runs the rebuild at 06:00 UTC in its own pod from the same image while the API serves, and
passes `SECOND_BRAIN_API_URL` so the rebuild tells the API to reopen when it finishes rather
than waiting for the next query to notice.

## What is still true

- One node. Everything runs on a single EC2 instance (PLAN.md section 6.2), and the index
  lives on that node's root disk through a k3s local-path volume, beside the vault copy and
  Prometheus's data. `DiskAlmostFull` watches that disk at 80 percent. Losing the node loses
  the index. It is rebuildable from the S3 vault copy, and the first full build on staging took
  about 22 minutes (`deploy/k8s/base/cronjob-indexer.yaml`).
- The fix heals a reader. It does not coordinate writers. Nothing serializes two writers beyond
  `concurrencyPolicy: Forbid` on the CronJob and the refusal to reopen during in-process
  ingestion.
- The 15-second cooldown means a query can still meet a stale view. That path is covered by one
  retry, not prevented.
- `IndexerStale` watches the job, not the data. A CronJob that keeps succeeding over a vault
  copy that stopped syncing from the desktop stays quiet, and the age gauge cannot tell a stale
  index from an unchanged vault.
- A full index build roughly doubles search latency on this node: week 3 measured p95 4.45 s and
  p50 2.61 s during the build against 1.97 s and 1.72 s after, with the node 72 percent busy
  (`deploy/monitoring/README.md`). `SearchLatencyHigh` went pending during that build and
  cleared by itself. The nightly run is incremental and much shorter.
- The verification on record in PR #25 ran against a copy of the live index with a backend on
  port 8010. The PR plans a post-merge smoke of the real backend from the UI; no result for that
  smoke is recorded in the PR.
- On the node, the reopen has only met a first build over an empty index. During week 3's build
  the canary scored 0.4 six minutes in and 10 of 10 once it finished, which is consistent with
  the API picking up the new index, but no reopen was recorded directly and a first build is not
  the nightly incremental write over a populated index. A partly built index reading as a
  quality drop is also the known false alarm on a first build.
- The strict probe's own reopen has never run. Staging's first run on 2026-09-18 used an image
  from before it, so the next fresh node is the first to exercise that path
  (`deploy/k8s/README.md`).
- Week 4's pipeline is built but has not run on a node (PLAN.md section 8).

## Game day

Game-day scenario 3, "Run the indexer while the API serves" (PLAN.md section 6.6), replays this
incident on purpose: the indexer writes the store while the API is serving, and the run should
show the index-age gauge move, the reopen from PR #25 pick up the new index, and the canary hit
rate stay at its baseline through the write. The scripts for the four scenarios belong in
`deploy/gameday/` (PLAN.md section 6.1) and are being written now; that directory is not on this
branch yet. Each scenario gets a runbook, and every run records time to alert and time to
recovery in `deploy/gameday/results.tsv`. The replay has not been run: as of 2026-09-19 the game
day is still the week 5 milestone. The result to want is a quiet one, since a healthy reopen
should raise no alert at all, so what the run has to prove is that the gauge moved, the canary
held, and search kept answering while a second process rewrote the store underneath it.
