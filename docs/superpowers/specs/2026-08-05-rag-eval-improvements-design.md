# RAG Retrieval Eval + Improvements — Design

**Date:** 2026-08-05
**Status:** Draft, pending review

## Goal

Make retrieval quality measurable, then improve it in steps that each show a
number moving. Every change lands as its own PR with before/after scores in
the description, and the README gains a "Retrieval quality" section with the
progression table.

## Non-goals

- No new repo or framework — the eval is a small module inside this repo.
- No cloud calls at query time — everything stays local, same as the rest of
  the app. (One-time model downloads from HuggingFace are already how
  `all-MiniLM-L6-v2` works today and are unchanged in kind.)
- No answer-quality (generation) eval in this phase — retrieval metrics only.
  Grading Qwen's prose needs an LLM judge and is a separate project.
- No frontend changes.

## Components

### 1. Shared retrieval module — `backend/retrieval.py`

Today the retrieval logic (embed query → Chroma query → scope filter) lives
inline in `run_query` in `backend/main.py`. Extract it into one function:

```
retrieve(query_text: str, scope: str, k: int) -> list[Candidate]
# Candidate: {source, title, chunk, distance/score}
```

Both the `/api/query` endpoint and the eval harness call this function, so
the eval can never drift from what the app actually does — the same reason
`indexer.py` was unified in PR #3.

Known gap (flagged in PR 1's final review): `/api/search` (⌘K command
search) still runs its own inline vector query and is not measured by the
eval. PR 2 must either fold it onto `retrieve()` or state the scope
limitation explicitly in the README. Resolved in PR 2: `/api/search` now
calls `retrieve()`.

### 2. Eval harness — `backend/eval/`

- **`dataset.jsonl`** — 30–50 cases, one per line:
  `{"question": "...", "expected_sources": ["03 Projects/Rightsize Design.md"]}`
  where `expected_sources` are vault-relative paths matching the chunk
  metadata `source` field. A question passes when any expected source
  appears in the top k.
- **`run_eval.py`** — loads the dataset, runs each question through
  `retrieve()`, and reports:
  - **hit-rate@4** — % of questions whose expected note appears in the top 4
  - **MRR@4** — mean reciprocal rank (1st place = 1.0, 4th = 0.25, miss = 0)
  Prints a per-case table and writes `results.json` for diffing between runs.
- **Ungradable cases:** if an expected source isn't in the index at all
  (renamed/deleted note), the case is reported separately as *ungradable*,
  not counted as a miss — stale dataset entries must not poison the numbers.

**Privacy decision (needs Bryan's sign-off):** the real dataset contains
private note titles and personal questions, so it is **gitignored**. The repo
commits `dataset.example.jsonl` (3 fake cases showing the format) plus the
harness. Published README numbers come from local runs against the real
dataset — the harness being public keeps them credible.

**Dataset authoring:** handwritten by Bryan (only he knows which note answers
which question). 30–50 cases; mix of exact-word questions ("what did I set
CHUNK_SIZE to"), paraphrase questions ("that project about model sizes"), and
chat-scope questions, since the improvements below target different failure
modes.

### 3. Improvement PRs

Each PR: one change, eval run before and after, both numbers in the PR
description. A change that regresses the numbers doesn't merge; a neutral
change merges only if it has a clear qualitative win, with the flat numbers
stated plainly — the README's register is honest.

**PR 1 — Eval harness + baseline.** No retrieval change. Adds
`retrieval.py`, `eval/`, CI smoke test, and the README table with the
baseline row.

**PR 2 — Heading-aware chunking.** `chunk_text()` in `backend/indexer.py`
currently slices every 500 words mid-sentence. Instead: split on markdown
headings first so each chunk is one coherent topic; sections longer than
CHUNK_SIZE words still fall back to the word-window internally; tiny adjacent
sections merge up to the cap. Chunk metadata gains a `heading` field (useful
for citations later). Requires a full reindex — PR notes the command.

**PR 3 — Hybrid BM25 + vector.** Pure vector search misses exact tokens
(project names, `CHUNK_SIZE`, error strings); BM25 nails them. Build an
in-memory BM25 index over the chunks (`rank_bm25`, built at startup and after
reindex), run both searches, merge with Reciprocal Rank Fusion (k=60). Scope
filters apply to both sides. BM25 build failure falls back to vector-only
with a logged warning.

**PR 4 — Cross-encoder reranker.** Two-stage retrieval: fused top-20 →
`cross-encoder/ms-marco-MiniLM-L-6-v2` (local, ~80MB) reads query+chunk
together and re-sorts → top 4 to Qwen. Lazy-loaded like the embedder; load
failure falls back to fused order. Latency budget: a few hundred ms on CPU
for 20 pairs, acceptable against a multi-second Qwen generation.

**PR 5 — Embedding model swap.** `all-MiniLM-L6-v2` (2021) →
`BAAI/bge-small-en-v1.5` (same 384-dim, materially better retrieval). Model
name moves to `config.py` / `.env`. Requires full reindex. Kept last so its
effect is measured on top of the structural fixes, not confounded with them.

## Error handling

- Eval: missing dataset file → clear message pointing at the example file.
- Retrieval fallbacks as above (BM25 → vector-only; reranker → fused order);
  both log so silent degradation can't hide.
- Reindex-requiring PRs must not corrupt an old index: chunk IDs already
  encode source path, and `index_vault(incremental=False)` wipes first.

## Testing

- Unit tests: heading chunker (splits, oversized-section fallback,
  frontmatter, merge-up), RRF fusion math, dataset loader/scorer.
- CI smoke test: a tiny fixture vault (3 fake notes) is indexed into a temp
  Chroma collection and one eval case runs end-to-end — CI never needs the
  private vault.
- Existing validation steps (`py_compile`, frontend build) unchanged.

## Rollout order

PR 1 → 2 → 3 → 4 → 5, sequential, each merged before the next starts so
every before/after pair is clean. Total: five PRs, one branch each.
