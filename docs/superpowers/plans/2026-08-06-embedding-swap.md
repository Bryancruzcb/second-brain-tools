# Embedding Model Swap (PR 5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Swap the 2021-era `all-MiniLM-L6-v2` bi-encoder for `BAAI/bge-small-en-v1.5` (same 384 dims, materially better retrieval), with the model name finally living in config. Targets the 5 remaining misses that never reach the fused top-20 — a first-stage recall problem only a better embedder can fix. Batch the carried cleanups: fused-pool membership per eval case, disable-tuple hoist, docstring fixes.

**Architecture:** `config.get_embedding_model()` (env `EMBEDDING_MODEL`) feeds all three production call sites (main.py loader, run_eval, rebuild_rag_index). `retrieval.retrieve()` gains an optional query-side prefix (env `EMBEDDING_QUERY_PREFIX`, default `""`) applied at encode time only — BGE models can benefit from their recommended query instruction, and the harness will A/B it before choosing the shipped default. The eval also records, per case, whether the expected note reached the fused top-20 pool, making ceiling analyses auditable from results.json.

**Tech Stack:** sentence-transformers (already installed) — bge-small-en-v1.5 is a ~130MB one-time local download. No new dependencies.

**Scope:** PR 5 — the last PR of `docs/superpowers/specs/2026-08-05-rag-eval-improvements-design.md`. Numbers to beat: hit-rate@4 80.0%, MRR@4 0.694.

## Global Constraints

- No cloud calls at query time (one-time model download, same as every model before it). Branch: `rag-embedding-swap` (already created).
- Embeddings from the two models are incompatible despite equal dimensions — a full reindex is mandatory before serving or evaluating, and the PR must say so.
- `backend/scripts/seed_demo_index.py` and `seed_real_structure.py` keep their hardcoded MiniLM (demo-seeding scripts, deliberately frozen; do not touch).
- The query prefix must affect ONLY the vector leg's encode input — never BM25 tokens, never stored chunk text, never the prompt sent to Qwen.
- Merge gate: regression doesn't merge; neutral needs plainly-stated numbers + qualitative win.
- Private dataset stays gitignored.

---

### Task 1: Config plumbing + query-prefix support

**Files:**
- Modify: `backend/config.py` (add `get_embedding_model()`, `get_query_prefix()`, `reranker_disabled()`; fix module docstring consumer list)
- Modify: `backend/main.py` (loader uses config for the model name; reranker loader uses `config.reranker_disabled`)
- Modify: `backend/eval/run_eval.py` (same two substitutions)
- Modify: `backend/scripts/rebuild_rag_index.py` (model name from config)
- Modify: `backend/retrieval.py` (query prefix at encode time; docstring "on the fused path" tighten)
- Test: `backend/tests/test_config.py` (new), `backend/tests/test_retrieval.py` (prefix test appended)

**Interfaces:**
- `config.get_embedding_model() -> str` — env `EMBEDDING_MODEL`, default `"BAAI/bge-small-en-v1.5"`.
- `config.get_query_prefix() -> str` — env `EMBEDDING_QUERY_PREFIX`, default `""` (Task 3's A/B decides whether the shipped default becomes BGE's instruction string; the plumbing lands value-neutral).
- `config.reranker_disabled(name: str) -> bool` — True for `""`/`"off"`/`"none"`/`"disabled"` after strip+lower; single source of truth replacing the tuple duplicated in main.py:111 and run_eval.py:91.
- `retrieval.retrieve()` embeds `config.get_query_prefix() + query_text`; everything else (BM25, candidates, stored text) sees the unprefixed query.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_config.py`:

```python
import config


def test_embedding_model_default_and_override(monkeypatch):
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    assert config.get_embedding_model() == "BAAI/bge-small-en-v1.5"
    monkeypatch.setenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    assert config.get_embedding_model() == "all-MiniLM-L6-v2"


def test_query_prefix_default_empty(monkeypatch):
    monkeypatch.delenv("EMBEDDING_QUERY_PREFIX", raising=False)
    assert config.get_query_prefix() == ""
    monkeypatch.setenv("EMBEDDING_QUERY_PREFIX", "query: ")
    assert config.get_query_prefix() == "query: "


def test_reranker_disabled_values():
    for value in ("", "off", "OFF", " none ", "Disabled"):
        assert config.reranker_disabled(value)
    assert not config.reranker_disabled("cross-encoder/ms-marco-MiniLM-L-6-v2")
```

Append to `backend/tests/test_retrieval.py`:

```python
class RecordingModel:
    def __init__(self):
        self.seen = []

    def encode(self, texts):
        import numpy as np
        self.seen.extend(texts)
        return np.zeros((len(texts), 4), dtype=np.float32)


def test_query_prefix_applies_to_vector_encode_only(monkeypatch):
    monkeypatch.setenv("EMBEDDING_QUERY_PREFIX", "query: ")
    rec = RecordingModel()
    lex = FakeLexical([
        {"id": "id_l", "source": "l.md", "title": "L", "chunk": "text", "score": 1.0},
    ])
    retrieval.retrieve_hybrid("find me", model=rec, collection=FakeCollection(CANNED), lexical=lex, k=2)
    assert rec.seen == ["query: find me"]          # vector leg sees the prefix
    assert lex.last_args[0] == "find me"           # BM25 leg does not
```

- [ ] **Step 2: Run to verify failure**

Run: `backend/venv/Scripts/python.exe -m pytest backend/tests/test_config.py backend/tests/test_retrieval.py -v`
Expected: config tests FAIL with `AttributeError: module 'config' has no attribute 'get_embedding_model'`; the prefix test FAILS (no prefix applied).

- [ ] **Step 3: Implement**

`backend/config.py` — append:

```python
def get_embedding_model() -> str:
    """Bi-encoder used to embed chunks and queries (EMBEDDING_MODEL to override).

    Changing this invalidates every stored embedding — run
    scripts/rebuild_rag_index.py --full afterward or retrieval silently
    compares vectors from different spaces.
    """
    return os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")


def get_query_prefix() -> str:
    """Instruction prepended to queries (not documents) at embed time.

    Some embedders (the BGE family) are trained with a query-side
    instruction; EMBEDDING_QUERY_PREFIX overrides, empty by default.
    """
    return os.environ.get("EMBEDDING_QUERY_PREFIX", "")


def reranker_disabled(name: str) -> bool:
    """Shared kill-switch semantics for RERANKER_MODEL values."""
    return name.strip().lower() in ("", "off", "none", "disabled")
```

Also update the module docstring's consumer list (line 3-5) to: "Centralizes configuration so main.py, indexer.py, eval/run_eval.py, and scripts/rebuild_rag_index.py all agree on paths and model choices, instead of each duplicating (and drifting from) its own copy."

`backend/main.py` — `_load_model_background` becomes:

```python
def _load_model_background():
    """Load sentence transformer in background thread."""
    global model
    name = config.get_embedding_model()
    logger.info("Loading Sentence Transformer model (%s) in background...", name)
    try:
        model = SentenceTransformer(name)
        logger.info("Sentence Transformer model loaded successfully in background.")
    except Exception as e:
        logger.error(f"Failed to load Sentence Transformer model: {e}")
```

and `_load_reranker_background`'s check becomes `if config.reranker_disabled(name):`.

`backend/eval/run_eval.py` — `model = SentenceTransformer(config.get_embedding_model())` (the "must match main.py's embedder" comment can go — it now matches by construction), and the reranker guard becomes `if not config.reranker_disabled(reranker_name):`.

`backend/scripts/rebuild_rag_index.py` — replace both the print and constructor:

```python
    model_name = config.get_embedding_model()
    print(f"Loading embedding model ({model_name})...")
    model = SentenceTransformer(model_name)
```

`backend/retrieval.py` — in `retrieve()`, the encode line becomes:

```python
    query_embedding = model.encode([config.get_query_prefix() + query_text]).tolist()
```

with `import config` added at the top of retrieval.py, and the module docstring line about the shared path left as is. Also tighten `retrieve_hybrid`'s docstring caveat to say "on the fused path" (per PR 4's review: the vector-only leg was always capped at HYBRID_DEPTH).

- [ ] **Step 4: Run tests**

Run: `backend/venv/Scripts/python.exe -m pytest backend/tests -q` → 70 passed (66 + 3 config + 1 prefix)
Run: `backend/venv/Scripts/python.exe -m py_compile backend/main.py backend/config.py backend/retrieval.py backend/eval/run_eval.py backend/scripts/rebuild_rag_index.py` → exit 0

- [ ] **Step 5: Commit**

```bash
git add backend/config.py backend/main.py backend/eval/run_eval.py backend/scripts/rebuild_rag_index.py backend/retrieval.py backend/tests/test_config.py backend/tests/test_retrieval.py
git commit -m "Move the embedding model into config and default to bge-small-en-v1.5"
```

---

### Task 2: Fused-pool membership in eval rows

**Files:**
- Modify: `backend/eval/run_eval.py`
- Modify: `backend/tests/test_eval_e2e.py`

**Interfaces:**
- Every gradable row gains `"expected_in_pool": bool` — whether any expected source appears in the fused top-RERANK_DEPTH pool (computed with `cross_encoder=None` so it reflects what the reranker was given); ungradable rows get `"expected_in_pool": None`. This makes PR 4's ceiling analysis (rerankable-miss vs absent-miss) auditable from results.json alone.

- [ ] **Step 1: Failing e2e assertions**

In `test_eval_end_to_end_on_fixture_vault`, append:

```python
    # Auditability: every gradable row records whether the expected note even
    # reached the fused top-20 the reranker saw. The fixture miss is an
    # in-pool miss (5 notes, pool of 20), so this pins the wiring both ways.
    assert hit_row["expected_in_pool"] is True
    assert miss_row["expected_in_pool"] is True
    assert by_q["note that does not exist anywhere"]["expected_in_pool"] is None
```

Run: `backend/venv/Scripts/python.exe -m pytest backend/tests/test_eval_e2e.py -v` — expect KeyError FAIL.

- [ ] **Step 2: Implement**

In `run()`: ungradable rows gain `"expected_in_pool": None`. For gradable cases, before scoring:

```python
        pool = unique_sources(retrieval.retrieve_hybrid(
            case["question"], model=model, collection=collection,
            lexical=lexical, cross_encoder=None, scope=case["scope"],
            k=retrieval.RERANK_DEPTH,
        ))
        expected_in_pool = any(e in pool for e in expected)
```

and add `"expected_in_pool": expected_in_pool` to the gradable row. (Yes, this embeds each query twice — 40 extra encodes per eval run is seconds, and keeping the pool probe out of the serving path is the point.)

- [ ] **Step 3: Run tests**

Run: `backend/venv/Scripts/python.exe -m pytest backend/tests -q` → 70 passed.

- [ ] **Step 4: Commit**

```bash
git add backend/eval/run_eval.py backend/tests/test_eval_e2e.py
git commit -m "Record whether each eval case reached the fused pool"
```

---

### Task 3: Reindex, A/B the query prefix, measure, record (controller-run)

- [ ] **Step 1:** Full reindex with the new embedder (first run downloads bge-small, ~130MB): from `backend/`, `venv/Scripts/python.exe scripts/rebuild_rag_index.py --full`.
- [ ] **Step 2:** Eval A/B: run `venv/Scripts/python.exe -m eval.run_eval` twice — once with `EMBEDDING_QUERY_PREFIX` unset, once with BGE's instruction (`"Represent this sentence for searching relevant passages: "`). Record both. If the prefix wins, set it as `get_query_prefix()`'s default (one-line change + adjust the config test) and state both numbers; if not, leave `""` and state both numbers anyway.
- [ ] **Step 3:** Check `expected_in_pool` on the results: how many of the previous 5 absent-from-pool misses now reach the pool? That's the claim this PR was aimed at — report it precisely.
- [ ] **Step 4:** README: final table row `| + bge-small-en-v1.5 embeddings (swapped from 2021-era MiniLM) | X% | 0.XX |`; update the diagnosis paragraph into a closing summary of the whole progression; note the reindex requirement.
- [ ] **Step 5:** Commit: `Record embedding swap retrieval numbers`.

---

### Task 4: Final review, push, PR

- [ ] **Step 1:** Whole-branch review (merge-base..HEAD package), most capable model; fix Important+ before push.
- [ ] **Step 2:** Full validation: suite green, py_compile, `cd frontend && npm run build`.
- [ ] **Step 3:** Push `rag-embedding-swap`, `gh pr create` — body: why (5 misses never reached the pool), what, the complete 5-row progression table, the A/B result, mandatory `rebuild_rag_index.py --full` + backend restart after merge, EMBEDDING_MODEL/EMBEDDING_QUERY_PREFIX env vars.
- [ ] **Step 4:** Watch CI to green (mind the ongoing GitHub Actions instability — retry infra failures); hand to Bryan for merge.
