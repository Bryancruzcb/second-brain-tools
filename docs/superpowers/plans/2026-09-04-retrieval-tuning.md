# Retrieval tuning run, 2026-09-04

Source: a private handoff brief (`Downloads/second-brain-rag-handoff.md`, not in
the repo). Every number in it was measured on 2026-09-04 against one 4,321-chunk
index. This run does not re-derive them; it builds on them.

Starting point, shipped config (depth 20, k=4): hit-rate@4 77.5%, MRR@4 0.715.
Reproduced exactly on a frozen copy of the index before any change, nine
misses: five expected notes never reach the fused pool, four are in the pool and
the reranker leaves them outside the top 4.

## What "done" means, item by item

1. **Config win.** `retrieval.py` defaults become depth 30 and top-k 6, each
   overridable by env (`TOP_K`, `HYBRID_DEPTH`, `RERANK_DEPTH`). On the frozen
   index `python -m eval.run_eval` prints hit-rate@6 82.5% and `--k 4` prints
   80.0%, the brief's table. README's retrieval-quality section says what
   reproduces today, with the date. pytest green. One PR.
2. **Reranker trial.** A committed sweep script builds the depth-30 candidate
   pools once and scores one model per process on identical pools. A candidate
   replaces `cross-encoder/ms-marco-MiniLM-L-6-v2` only if it reaches hit@4
   82.5% or better (one whole case over 80.0%) and its median per-query rerank
   time stays under 1.5 s in interleaved A/B/A/B timing against the current
   model. Otherwise the negative result is written down and the default stays.
   Candidates: ms-marco-MiniLM-L-12-v2 (33M), mxbai-rerank-xsmall-v1 (71M),
   jina-reranker-v1-turbo-en (38M), mxbai-rerank-base-v1 (184M). ONNX
   quantisation of the current model is left out: same weights cannot beat
   80.0%, it only buys latency.
3. **Contextual chunk headers.** Folder path, note title and section heading
   prepended to each chunk at index time, behind `CHUNK_SCHEME`, default off.
   Two fresh full rebuilds into scratch Chroma paths, one per scheme, scored
   with identical config. Ships default-on only if hit@4 improves by at least
   5.0 points (two cases), which clears the plus-or-minus one case rebuild
   jitter the README already discloses.
4. **Eval in CI.** CI cannot read the private vault, so the watch has two
   halves. A committed scorecard (metrics, config fingerprint, index census,
   dataset hash; no questions, no note paths) that a test compares with the
   shipped config and with the README block, so changing retrieval config
   without re-running the eval fails CI. And an eval step in the nightly
   archive job, the only process that sees the corpus move, which appends to a
   local history file and prints a drift warning.

## Scope and rigor

Roughly 60 lines of code for item 1, a 200-line sweep script for item 2, 80
lines plus tests for item 3, 200 lines plus tests for item 4. Wall-clock is
dominated by model runs, which are serialised: one eval is about 2.5 minutes,
one full re-embed of 4,321 chunks on CPU is several minutes.

Rigor is highest on measurement validity, because that is where the brief lost
its time. Gates:

- Every quoted number comes from a committed script run against the frozen
  index copy, never from a hand-run one-off.
- One cross-encoder per process. The machine had 2.5 GB free at start.
- Latency claims only from interleaved rounds; whichever model runs first
  absorbs lazy-init cost.
- Nothing is timed while another model process runs.
- Offline flags set for every model run (`HF_HUB_OFFLINE`,
  `TRANSFORMERS_OFFLINE`, `TOKENIZERS_PARALLELISM=false`, `PYTHONUTF8=1`).
- The main checkout stays on `main`. The nightly archive job runs the indexer
  from it at 21:00, so a half-finished indexer change there would touch the
  real index.

## Order and seams

1. Baseline on unmodified `main` against the frozen index (done).
2. Item 1 on `rag-depth30-topk6`, with three verification evals (k=6, 4, 8).
3. Item 2 on `rag-reranker-sweep`, serial, model-bound.
4. Item 3 code by a worker in its own worktree (`rag-context-headers`); the two
   rebuilds and their evals run afterwards, serial.
5. Item 4 code by a worker in its own worktree (`rag-eval-scorecard`); the
   scorecard itself is recorded once the final config is known.

Workers only write code and tests. They never load a model, never touch
`backend/chroma_db`, never push.

## Decision trail

One TSV, one row per decision, kept with the show-me-your-work format. Working
copy lives outside the repo during the run and is committed as
`docs/eval/decisions-2026-09-04.tsv` with the last PR.

## Checklist

- [x] Freeze the index copy and reproduce the baseline (77.5% / 0.715)
- [x] Item 1: env-driven knobs, tests first, suite green
- [ ] Item 1: k=6 / k=4 / k=8 evals reproduce the brief's table
- [ ] Item 1: README retrieval-quality section re-measured, PR opened
- [ ] Item 2: sweep script, pools dumped once, five models scored
- [ ] Item 2: interleaved timing for any candidate that clears 82.5%
- [ ] Item 2: results written down, default changed only on both gates
- [ ] Item 3: header composition behind a flag, tests first
- [ ] Item 3: two rebuilds, two evals, decision on the 5-point rule
- [ ] Item 4: scorecard, CI test, README block, nightly drift step
- [ ] Trail audited against the transcript, reviewed by a second model
