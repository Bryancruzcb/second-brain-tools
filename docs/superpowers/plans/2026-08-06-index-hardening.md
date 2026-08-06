# Index Hardening (issues #8 + #12) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the two observability traps the eval-sequence reviews filed: #8 (index_vault reports success when every embedding batch fails) and #12 (an embedding-model swap without a full rebuild silently mixes vector spaces). One PR, `Closes #8` / `Closes #12`.

**Architecture:** `indexer.index_vault` gains `batches_failed` in its summary and embedding-model provenance: a `--full` rebuild stamps `config.get_embedding_model()` into the collection metadata; an incremental run **aborts** on a stamp mismatch (continuing would permanently mix vector spaces — the nightly job is exactly the caller that would do this). Callers surface it: `rebuild_rag_index.py` exits nonzero on failure/abort, backend startup logs a loud error on mismatch (still serves), the eval hard-exits (its numbers would be garbage).

**Tech Stack:** existing; Chroma `collection.modify(metadata=...)` / `collection.metadata` for the stamp. No new dependencies. No retrieval-behavior change — eval numbers are untouched, no reindex-for-quality needed (a local `--full` after merge stamps the index).

## Global Constraints

- No cloud calls. Branch: `rag-hardening` (already created).
- Retrieval behavior unchanged — the full suite's retrieval/eval assertions must pass untouched.
- Mismatch policy, exactly: incremental index run → **abort** (log + summary flag, no writes); backend startup → **loud error, still serve**; eval `main()` → **hard exit**; unstamped index → **warn only** everywhere (pre-#12 indexes are legal), and incremental runs do NOT stamp (stamping without a full re-embed would assert false provenance).
- Stamp key: `"embedding_model"` in the collection metadata dict; preserve any other keys present (read-modify-write).
- `summary["batches_failed"]` counts failed flush batches; `summary["aborted"]` (string reason) present only when the mismatch abort fires.
- Commit messages and PR body reference the issues; PR body carries `Closes #8` and `Closes #12`.

---

### Task 1: indexer.py — batches_failed + provenance stamp/abort

**Files:**
- Modify: `backend/indexer.py` (`flush()` counting; provenance block at the top of `index_vault`)
- Test: `backend/tests/test_indexer.py` (new)

**Interfaces:**
- `index_vault` summary gains `"batches_failed": int` (always present, 0 on success). On incremental-with-mismatch: returns immediately with `"aborted": "embedding model mismatch: index stamped '<stamped>', configured '<configured>'; run scripts/rebuild_rag_index.py --full"` added to the summary, all other counters 0, no collection writes.
- Full rebuild: after the wipe, `collection.modify(metadata={**(collection.metadata or {}), "embedding_model": config.get_embedding_model()})`.
- Unstamped + incremental: `log("Index has no embedding-model stamp; run scripts/rebuild_rag_index.py --full to stamp it.")` and proceed.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_indexer.py`:

```python
import os

import chromadb
import pytest

import config
import indexer
from tests.fakes import BagOfWordsEmbedder

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


class ExplodingModel:
    def encode(self, texts):
        raise RuntimeError("model exploded")


@pytest.fixture()
def vault_env(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", os.path.join(FIXTURES, "vault"))
    monkeypatch.setenv("EMBEDDING_MODEL", "model-a")
    return chromadb.EphemeralClient().get_or_create_collection("hardening")


def test_full_rebuild_stamps_embedding_model(vault_env):
    collection = vault_env
    summary = indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=False, log=lambda *_: None)
    assert summary["batches_failed"] == 0
    assert summary["chunks_written"] >= 5
    assert collection.metadata["embedding_model"] == "model-a"


def test_incremental_aborts_on_stamp_mismatch(vault_env, monkeypatch):
    collection = vault_env
    indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=False, log=lambda *_: None)
    before = collection.count()

    monkeypatch.setenv("EMBEDDING_MODEL", "model-b")
    # Touch a file's mtime so a non-aborting incremental would re-embed it.
    target = os.path.join(FIXTURES, "vault", "Sourdough Starter.md")
    os.utime(target, None)

    summary = indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=True, log=lambda *_: None)
    assert "aborted" in summary
    assert "model-a" in summary["aborted"] and "model-b" in summary["aborted"]
    assert summary["chunks_written"] == 0
    assert collection.count() == before  # nothing was written or deleted


def test_incremental_with_matching_stamp_proceeds(vault_env):
    collection = vault_env
    indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=False, log=lambda *_: None)
    summary = indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=True, log=lambda *_: None)
    assert "aborted" not in summary
    assert summary["files_scanned"] >= 5


def test_unstamped_incremental_warns_but_proceeds(vault_env):
    collection = vault_env
    messages = []
    summary = indexer.index_vault(collection, BagOfWordsEmbedder(), incremental=True, log=messages.append)
    assert "aborted" not in summary
    assert any("stamp" in str(m) for m in messages)
    assert collection.metadata is None or "embedding_model" not in (collection.metadata or {})


def test_failed_batches_are_counted(vault_env):
    collection = vault_env
    summary = indexer.index_vault(collection, ExplodingModel(), incremental=False, log=lambda *_: None)
    assert summary["batches_failed"] >= 1
    assert summary["chunks_written"] == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `backend/venv/Scripts/python.exe -m pytest backend/tests/test_indexer.py -v`
Expected: FAIL — `batches_failed` KeyError, missing stamp, no abort.

- [ ] **Step 3: Implement in `backend/indexer.py`**

At the top of `index_vault`, after `vault_path = config.get_vault_path()`:

```python
    configured_model = config.get_embedding_model()
    stamped_model = (collection.metadata or {}).get("embedding_model")
    if incremental and stamped_model and stamped_model != configured_model:
        # Continuing would embed new chunks with a different model into the
        # same vector space — silent, permanent corruption. Refuse.
        reason = (
            f"embedding model mismatch: index stamped '{stamped_model}', "
            f"configured '{configured_model}'; run scripts/rebuild_rag_index.py --full"
        )
        log(f"ABORTING incremental index: {reason}")
        return {
            "files_scanned": 0, "files_skipped": 0, "files_reindexed": 0,
            "files_pruned": 0, "chunks_written": 0, "batches_failed": 0,
            "aborted": reason,
        }
    if incremental and not stamped_model:
        log("Index has no embedding-model stamp; run scripts/rebuild_rag_index.py --full to stamp it.")
```

Add `"batches_failed": 0` to the summary dict. In `flush()`'s except branch, add `summary["batches_failed"] += 1` beside the existing log call.

In the full-rebuild branch (after the wipe succeeds), stamp:

```python
            collection.modify(metadata={**(collection.metadata or {}), "embedding_model": configured_model})
```

At the end, extend the completion log with the failure count when nonzero:

```python
    if summary["batches_failed"]:
        log(f"WARNING: {summary['batches_failed']} embedding batch(es) FAILED — the index is incomplete.")
```

- [ ] **Step 4: Run tests**

Run: `backend/venv/Scripts/python.exe -m pytest backend/tests/test_indexer.py -v` → 5 passed
Run: `backend/venv/Scripts/python.exe -m pytest backend/tests -q` → 75 passed (70 + 5)

- [ ] **Step 5: Commit**

```bash
git add backend/indexer.py backend/tests/test_indexer.py
git commit -m "Count failed embed batches and refuse cross-model incremental indexing (#8, #12)"
```

---

### Task 2: Callers — exit codes, startup check, eval refusal

**Files:**
- Modify: `backend/scripts/rebuild_rag_index.py` (stamped-vs-configured print; nonzero exit on failure/abort/zero-write)
- Modify: `backend/main.py` (`_load_fast_sync` mismatch error-log; `run_ingestion_sync` logs `aborted`/`batches_failed`)
- Modify: `backend/eval/run_eval.py` (`main()` hard-exits on mismatch, warns on unstamped)
- Test: `backend/tests/test_eval_e2e.py` — none needed (run() untouched); `backend/tests/test_indexer.py` — none added here.

**Interfaces:**
- `rebuild_rag_index.py`: before indexing, print `Index stamp: <stamped or '(unstamped)'> | configured: <configured>`. After: `sys.exit(1)` when `summary.get("aborted")` or `summary["batches_failed"] > 0` or (`summary["chunks_written"] == 0 and summary["files_reindexed"] > 0`), each with a one-line reason printed.
- `main.py` `_load_fast_sync`: after the collection loads, if stamped and mismatched → `logger.error("Embedding model mismatch: index stamped %r but EMBEDDING_MODEL is %r — vector search will return garbage until scripts/rebuild_rag_index.py --full is run.", ...)`; unstamped → `logger.warning(...)` one-liner. Backend still serves.
- `main.py` `run_ingestion_sync`: if `summary.get("aborted")` → `logger.error(summary["aborted"])`; if `summary.get("batches_failed")` → error-level count log.
- `run_eval.py` `main()`: after building the collection, mismatch → print the reason and `sys.exit(1)`; unstamped → print a warning and continue.

- [ ] **Step 1: Implement all four call sites** (no new tests: the logic is one comparison per site, the shared behavior is pinned by Task 1's tests; endpoint/e2e suites must stay green proving no serving-path regression)

- [ ] **Step 2: Verify**

Run: `backend/venv/Scripts/python.exe -m pytest backend/tests -q` → 75 passed
Run: `backend/venv/Scripts/python.exe -m py_compile backend/main.py backend/indexer.py backend/eval/run_eval.py backend/scripts/rebuild_rag_index.py` → exit 0
Manual check (backend venv, from `backend/`): `venv/Scripts/python.exe scripts/rebuild_rag_index.py` (incremental, real index — expect the stamp line, and since the live index is not yet stamped, the warn-but-proceed path; exit 0).

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/rebuild_rag_index.py backend/main.py backend/eval/run_eval.py
git commit -m "Surface index failures and model mismatches at every call site (#8, #12)"
```

---

### Task 3: Stamp the live index, validate, review, PR (controller-run)

- [ ] **Step 1:** From `backend/`: `venv/Scripts/python.exe scripts/rebuild_rag_index.py --full` — stamps the local index with `BAAI/bge-small-en-v1.5`. Then rerun the incremental path once to confirm the matching-stamp fast path (exit 0, no warnings).
- [ ] **Step 2:** Sanity: `venv/Scripts/python.exe -m eval.run_eval` still reports 80.0% / 0.713 (provenance changes must not move retrieval numbers).
- [ ] **Step 3:** Whole-branch review; fix Important+; full validation (suite, py_compile, frontend build).
- [ ] **Step 4:** Push `rag-hardening`; PR titled "Index hardening: loud failures and embedding-model provenance" with `Closes #8` / `Closes #12`, before/after behavior table (silent vs loud per scenario), and the after-merge note (run `--full` once per machine to stamp). Watch CI (GH outage may still delay — retry infra failures).
