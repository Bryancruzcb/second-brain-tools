# RAG Eval Harness + Baseline (PR 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract retrieval into a shared module, build a retrieval eval harness (hit-rate@4 / MRR@4), wire it into CI with a fixture vault, and publish the baseline in the README.

**Architecture:** `backend/retrieval.py` becomes the single retrieval code path called by both `/api/query` and the eval. `backend/eval/` holds pure scoring + dataset loading + a CLI runner. Tests live in `backend/tests/` with a deterministic bag-of-words embedder so CI never downloads a model or touches the private vault. The real dataset is gitignored; the repo ships a 3-case example.

**Tech Stack:** Python 3.10+, FastAPI, ChromaDB 1.5.9, sentence-transformers 5.6.0, pytest (new dev dep).

**Scope:** This plan is PR 1 of the 5-PR sequence in `docs/superpowers/specs/2026-08-05-rag-eval-improvements-design.md`. PRs 2–5 (chunking, hybrid, reranker, embedding swap) get their own plans once the baseline numbers exist.

## Global Constraints

- No cloud calls at query time — all retrieval/generation stays local (repo's core guarantee).
- The private dataset (`backend/eval/dataset.jsonl`) and results (`backend/eval/results.json`) are **gitignored**; only `dataset.example.jsonl` is committed.
- `/api/query` behavior must not change in this PR — pure refactor plus harness.
- Follow `config.py`'s env-var-override pattern for any new configuration.
- README register: plain, honest, first-person — no "production-grade" language.
- All work on branch `rag-eval-improvements` (already exists, contains the spec).

---

### Task 1: Scoring module (pure functions)

**Files:**
- Create: `backend/eval/__init__.py` (empty)
- Create: `backend/eval/scoring.py`
- Create: `backend/tests/conftest.py`
- Test: `backend/tests/test_scoring.py`

**Interfaces:**
- Produces: `unique_sources(candidates: list[dict]) -> list[str]` (candidates have a `"source"` key, ordered best-first); `score_case(retrieved_sources: list[str], expected_sources: list[str], k: int = 4) -> dict` returning `{"hit": bool, "reciprocal_rank": float, "rank": int | None}`; `aggregate(case_results: list[dict]) -> dict` returning `{"hit_rate": float, "mrr": float, "cases": int}`.

- [ ] **Step 1: Create test scaffolding**

`backend/tests/conftest.py` — makes `import retrieval` / `import eval.scoring` work from any pytest invocation directory:

```python
import os
import sys

# Tests import backend modules (retrieval, eval.*) directly, so put the
# backend directory itself on sys.path regardless of where pytest runs from.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

Create empty `backend/eval/__init__.py`.

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_scoring.py`:

```python
from eval.scoring import aggregate, score_case, unique_sources


def test_unique_sources_dedupes_preserving_order():
    candidates = [
        {"source": "a.md"}, {"source": "b.md"}, {"source": "a.md"}, {"source": "c.md"},
    ]
    assert unique_sources(candidates) == ["a.md", "b.md", "c.md"]


def test_hit_at_rank_one():
    result = score_case(["a.md", "b.md"], ["a.md"], k=4)
    assert result == {"hit": True, "reciprocal_rank": 1.0, "rank": 1}


def test_hit_at_rank_three():
    result = score_case(["x.md", "y.md", "a.md"], ["a.md"], k=4)
    assert result["hit"] is True
    assert result["reciprocal_rank"] == 1.0 / 3
    assert result["rank"] == 3


def test_miss_scores_zero():
    result = score_case(["x.md", "y.md"], ["a.md"], k=4)
    assert result == {"hit": False, "reciprocal_rank": 0.0, "rank": None}


def test_expected_source_beyond_k_is_a_miss():
    retrieved = ["1.md", "2.md", "3.md", "4.md", "a.md"]
    result = score_case(retrieved, ["a.md"], k=4)
    assert result["hit"] is False


def test_any_of_multiple_expected_sources_counts():
    result = score_case(["x.md", "b.md"], ["a.md", "b.md"], k=4)
    assert result["rank"] == 2


def test_aggregate_means():
    results = [
        {"hit": True, "reciprocal_rank": 1.0, "rank": 1},
        {"hit": True, "reciprocal_rank": 0.5, "rank": 2},
        {"hit": False, "reciprocal_rank": 0.0, "rank": None},
    ]
    agg = aggregate(results)
    assert agg["cases"] == 3
    assert agg["hit_rate"] == 2 / 3
    assert agg["mrr"] == (1.0 + 0.5 + 0.0) / 3


def test_aggregate_empty_is_zero():
    assert aggregate([]) == {"hit_rate": 0.0, "mrr": 0.0, "cases": 0}
```

- [ ] **Step 3: Run tests to verify they fail**

Run (from repo root, backend venv active): `python -m pytest backend/tests/test_scoring.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'eval.scoring'`

- [ ] **Step 4: Implement scoring.py**

`backend/eval/scoring.py`:

```python
"""Pure scoring functions for the retrieval eval. No I/O, no Chroma.

Metrics are note-level: chunk candidates are deduped to unique note paths
first (unique_sources), then rank = 1-based position of the first expected
note. This mirrors what the app does — Qwen sees the notes behind the top-k
chunks, so a note whose chunks fill positions 1-3 is one result, not three.
"""


def unique_sources(candidates):
    """Ordered unique note paths from chunk-level candidates (best first)."""
    seen = []
    for candidate in candidates:
        source = candidate["source"]
        if source not in seen:
            seen.append(source)
    return seen


def score_case(retrieved_sources, expected_sources, k=4):
    """Score one case. retrieved_sources: ordered unique note paths.

    Returns {"hit": bool, "reciprocal_rank": float, "rank": int | None},
    rank being the 1-based position of the first expected source within the
    top k, or None on a miss.
    """
    expected = set(expected_sources)
    for i, source in enumerate(retrieved_sources[:k], start=1):
        if source in expected:
            return {"hit": True, "reciprocal_rank": 1.0 / i, "rank": i}
    return {"hit": False, "reciprocal_rank": 0.0, "rank": None}


def aggregate(case_results):
    """Mean hit-rate and MRR over gradable cases; zeros when empty."""
    if not case_results:
        return {"hit_rate": 0.0, "mrr": 0.0, "cases": 0}
    hits = sum(1 for r in case_results if r["hit"])
    mrr = sum(r["reciprocal_rank"] for r in case_results) / len(case_results)
    return {"hit_rate": hits / len(case_results), "mrr": mrr, "cases": len(case_results)}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_scoring.py -v`
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add backend/eval/__init__.py backend/eval/scoring.py backend/tests/conftest.py backend/tests/test_scoring.py
git commit -m "Add note-level hit-rate/MRR scoring for the retrieval eval"
```

---

### Task 2: Dataset loader + example file

**Files:**
- Create: `backend/eval/dataset.py`
- Create: `backend/eval/dataset.example.jsonl`
- Test: `backend/tests/test_dataset.py`

**Interfaces:**
- Produces: `load_dataset(path: str) -> list[dict]` where each dict is `{"question": str, "expected_sources": list[str], "scope": str}` (scope defaults to `"notes"`); `DatasetError(ValueError)` raised on any invalid line, message includes path and line number.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_dataset.py`:

```python
import pytest

from eval.dataset import DatasetError, load_dataset


def write(tmp_path, text):
    p = tmp_path / "dataset.jsonl"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_loads_valid_cases_and_defaults_scope(tmp_path):
    path = write(tmp_path, (
        '{"question": "what is X?", "expected_sources": ["03 Projects/X.md"]}\n'
        '\n'  # blank lines are skipped
        '{"question": "chat Q", "expected_sources": ["05 AI Chats/a.md"], "scope": "chats"}\n'
    ))
    cases = load_dataset(path)
    assert len(cases) == 2
    assert cases[0] == {"question": "what is X?",
                        "expected_sources": ["03 Projects/X.md"], "scope": "notes"}
    assert cases[1]["scope"] == "chats"


def test_invalid_json_reports_line_number(tmp_path):
    path = write(tmp_path, '{"question": "ok", "expected_sources": ["a.md"]}\n{broken\n')
    with pytest.raises(DatasetError, match=":2:"):
        load_dataset(path)


def test_empty_question_rejected(tmp_path):
    path = write(tmp_path, '{"question": "  ", "expected_sources": ["a.md"]}\n')
    with pytest.raises(DatasetError, match="question"):
        load_dataset(path)


def test_missing_expected_sources_rejected(tmp_path):
    path = write(tmp_path, '{"question": "q", "expected_sources": []}\n')
    with pytest.raises(DatasetError, match="expected_sources"):
        load_dataset(path)


def test_bad_scope_rejected(tmp_path):
    path = write(tmp_path, '{"question": "q", "expected_sources": ["a.md"], "scope": "everything"}\n')
    with pytest.raises(DatasetError, match="scope"):
        load_dataset(path)


def test_empty_dataset_rejected(tmp_path):
    path = write(tmp_path, "\n")
    with pytest.raises(DatasetError, match="empty"):
        load_dataset(path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest backend/tests/test_dataset.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'eval.dataset'`

- [ ] **Step 3: Implement dataset.py**

`backend/eval/dataset.py`:

```python
"""Load and validate the eval dataset.

Format: JSONL, one case per line:
    {"question": "...", "expected_sources": ["vault/relative/path.md"], "scope": "notes"}
expected_sources are vault-relative paths matching the chunk metadata
"source" field; scope is optional ("notes" default, or "chats"/"all").
"""
import json

VALID_SCOPES = ("notes", "chats", "all")


class DatasetError(ValueError):
    pass


def load_dataset(path):
    cases = []
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise DatasetError(f"{path}:{lineno}: invalid JSON: {e}") from e

            question = obj.get("question")
            if not isinstance(question, str) or not question.strip():
                raise DatasetError(f"{path}:{lineno}: 'question' must be a non-empty string")

            expected = obj.get("expected_sources")
            if (not isinstance(expected, list) or not expected
                    or not all(isinstance(s, str) and s.strip() for s in expected)):
                raise DatasetError(
                    f"{path}:{lineno}: 'expected_sources' must be a non-empty list of strings")

            scope = obj.get("scope", "notes")
            if scope not in VALID_SCOPES:
                raise DatasetError(
                    f"{path}:{lineno}: 'scope' must be one of {VALID_SCOPES}, got {scope!r}")

            cases.append({
                "question": question.strip(),
                "expected_sources": [s.strip() for s in expected],
                "scope": scope,
            })
    if not cases:
        raise DatasetError(f"{path}: dataset is empty")
    return cases
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_dataset.py -v`
Expected: 6 passed

- [ ] **Step 5: Create the example dataset**

`backend/eval/dataset.example.jsonl` (fake cases showing the format — the real, private dataset is `dataset.jsonl`, gitignored):

```jsonl
{"question": "what temperature do I keep my sourdough starter at?", "expected_sources": ["02 Areas/Sourdough Starter.md"]}
{"question": "which project decided to use reciprocal rank fusion?", "expected_sources": ["03 Projects/Search Rework.md", "03 Projects/Search Rework Notes.md"]}
{"question": "what did that chat about borrow checker errors conclude?", "expected_sources": ["05 AI Chats/Claude/Rust/Borrow Checker Session.md"], "scope": "chats"}
```

- [ ] **Step 6: Commit**

```bash
git add backend/eval/dataset.py backend/eval/dataset.example.jsonl backend/tests/test_dataset.py
git commit -m "Add eval dataset loader with per-line validation and example file"
```

---

### Task 3: Shared retrieval module, /api/query refactored onto it

**Files:**
- Create: `backend/retrieval.py`
- Modify: `backend/main.py:22` (import), `backend/main.py:466-522` (run_query body)
- Test: `backend/tests/test_retrieval.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `retrieval.TOP_K = 4`; `retrieval.scope_filter(scope: str) -> dict | None`; `retrieval.retrieve(query_text: str, *, model, collection, scope: str = "notes", k: int = TOP_K) -> list[dict]` returning best-first `{"source": str, "title": str, "chunk": str, "distance": float}`. `model` is anything with `.encode(list[str])` returning an array with `.tolist()`; `collection` is a Chroma collection.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_retrieval.py`:

```python
import retrieval


class FakeModel:
    def encode(self, texts):
        import numpy as np
        return np.zeros((len(texts), 4), dtype=np.float32)


class FakeCollection:
    """Records query kwargs and returns a canned Chroma-shaped result."""
    def __init__(self, result):
        self.result = result
        self.last_kwargs = None

    def query(self, **kwargs):
        self.last_kwargs = kwargs
        return self.result


CANNED = {
    "documents": [["chunk one text", "chunk two text"]],
    "metadatas": [[{"source": "a.md", "title": "A"}, {"source": "b.md", "title": "B"}]],
    "distances": [[0.1, 0.4]],
}


def test_retrieve_parses_chroma_results_into_candidates():
    coll = FakeCollection(CANNED)
    out = retrieval.retrieve("q", model=FakeModel(), collection=coll)
    assert out == [
        {"source": "a.md", "title": "A", "chunk": "chunk one text", "distance": 0.1},
        {"source": "b.md", "title": "B", "chunk": "chunk two text", "distance": 0.4},
    ]


def test_retrieve_passes_k_and_scope_filter():
    coll = FakeCollection(CANNED)
    retrieval.retrieve("q", model=FakeModel(), collection=coll, scope="chats", k=7)
    assert coll.last_kwargs["n_results"] == 7
    assert coll.last_kwargs["where"] == {"category": "chat"}


def test_retrieve_handles_empty_results():
    coll = FakeCollection({"documents": [[]], "metadatas": [[]], "distances": [[]]})
    assert retrieval.retrieve("q", model=FakeModel(), collection=coll) == []


def test_scope_filters():
    assert retrieval.scope_filter("chats") == {"category": "chat"}
    assert retrieval.scope_filter("notes") == {"category": {"$ne": "chat"}}
    assert retrieval.scope_filter("all") is None


def test_missing_metadata_gets_defaults():
    coll = FakeCollection({
        "documents": [["text"]],
        "metadatas": [[None]],
        "distances": [[0.2]],
    })
    out = retrieval.retrieve("q", model=FakeModel(), collection=coll)
    assert out[0]["source"] == ""
    assert out[0]["title"] == "Untitled Note"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest backend/tests/test_retrieval.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'retrieval'`

- [ ] **Step 3: Implement retrieval.py**

`backend/retrieval.py`:

```python
"""Shared retrieval: the one code path both /api/query and the eval use.

Extracted from main.py's run_query so the eval harness measures exactly
what the app does — same reason indexer.py was unified in PR #3.
"""

TOP_K = 4


def scope_filter(scope):
    """Chroma where-filter for a search scope ("notes" | "chats" | "all")."""
    if scope == "chats":
        return {"category": "chat"}
    if scope == "notes":
        return {"category": {"$ne": "chat"}}
    return None


def retrieve(query_text, *, model, collection, scope="notes", k=TOP_K):
    """Embed query_text and return the top-k chunk candidates, best first.

    Returns a list of {"source", "title", "chunk", "distance"} dicts.
    """
    query_embedding = model.encode([query_text]).tolist()
    results = collection.query(
        query_embeddings=query_embedding,
        n_results=k,
        where=scope_filter(scope),
    )
    candidates = []
    if results and results.get("documents") and results["documents"]:
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        dists = (results.get("distances") or [[0.0] * len(docs)])[0]
        for doc, meta, dist in zip(docs, metas, dists):
            meta = meta or {}
            candidates.append({
                "source": meta.get("source", ""),
                "title": meta.get("title", "Untitled Note"),
                "chunk": doc,
                "distance": float(dist),
            })
    return candidates
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest backend/tests/test_retrieval.py -v`
Expected: 5 passed

- [ ] **Step 5: Refactor run_query onto retrieve()**

In `backend/main.py`, add the import after line 22 (`import indexer`):

```python
import retrieval
```

Then replace the body of `run_query` from the line `recent_user_turns = ...` (line 471) through the `context_chunks.append(...)` loop (line 522) with:

```python
        recent_user_turns = [m["content"] for m in history if m["role"] == "user"][-2:]
        retrieval_text = "\n".join(recent_user_turns + [query_text])

        # 2. Retrieve context chunks
        if request.context_nodes and len(request.context_nodes) > 0:
            # Specifically requested nodes bypass search entirely.
            raw = chroma_collection.get(where={"source": {"$in": request.context_nodes}})
            candidates = [
                {
                    "source": (meta or {}).get("source", ""),
                    "title": (meta or {}).get("title", "Untitled Note"),
                    "chunk": doc,
                    "distance": 0.0,
                }
                for doc, meta in zip(raw.get("documents") or [], raw.get("metadatas") or [])
            ]
        else:
            candidates = retrieval.retrieve(
                retrieval_text,
                model=model,
                collection=chroma_collection,
                scope=request.scope or "notes",
            )

        # 3. Format context source items
        sources = []
        context_chunks = []
        for c in candidates:
            sources.append({
                "title": c["title"],
                "source": c["source"],
                "snippet": c["chunk"][:400] + "..." if len(c["chunk"]) > 400 else c["chunk"],
                "distance": c["distance"],
            })
            context_chunks.append(f"From Note: {c['title']}\nContent: {c['chunk']}")
```

Keep everything above (history/embed comment block header `# 1.`) and below (`# 4. Generate prompt context` onward) unchanged. Note the comment numbering: the old `# 1. Embed the retrieval text` comment stays as-is above `recent_user_turns` — it still describes why user turns are folded in.

- [ ] **Step 6: Verify the refactor**

Run: `python -m py_compile backend/main.py backend/retrieval.py`
Expected: exit 0, no output.

Run: `python -m pytest backend/tests -q`
Expected: all passed.

Manual smoke (backend venv, Ollama not required for retrieval): start `uvicorn main:app --port 8000` from `backend/`, then:

```bash
curl -s -X POST http://localhost:8000/api/query -H "Content-Type: application/json" -d '{"query": "test question", "scope": "notes"}'
```

Expected: a JSON response with `sources` populated (answer may be an Ollama error if Ollama is off — that's fine, retrieval ran). Stop the server after.

- [ ] **Step 7: Commit**

```bash
git add backend/retrieval.py backend/main.py backend/tests/test_retrieval.py
git commit -m "Extract shared retrieval module so the eval measures the real query path"
```

---

### Task 4: Eval runner CLI + end-to-end fixture test

**Files:**
- Create: `backend/eval/run_eval.py`
- Create: `backend/tests/fakes.py`
- Create: `backend/tests/fixtures/vault/Sourdough Starter.md`
- Create: `backend/tests/fixtures/vault/Rust Borrow Checker.md`
- Create: `backend/tests/fixtures/vault/Marathon Training.md`
- Create: `backend/tests/fixtures/dataset.jsonl`
- Test: `backend/tests/test_eval_e2e.py`

**Interfaces:**
- Consumes: `load_dataset` (Task 2), `score_case`/`unique_sources`/`aggregate` (Task 1), `retrieval.retrieve`/`TOP_K` (Task 3), `indexer.index_vault(collection, model, incremental)` (existing).
- Produces: `run_eval.run(cases, *, model, collection, k) -> tuple[list[dict], dict]` — per-case rows (`{"question", "status": "hit"|"miss"|"ungradable", "rank", "expected_sources"}`) and a summary (`{"hit_rate", "mrr", "cases", "ungradable", "k"}`); `python -m eval.run_eval` CLI.

- [ ] **Step 1: Create fixture vault and fixture dataset**

Three tiny notes with disjoint vocabulary so a bag-of-words embedder ranks them correctly.

`backend/tests/fixtures/vault/Sourdough Starter.md`:

```markdown
# Sourdough Starter

Feed the sourdough starter every morning with equal parts flour and water.
Keep the starter jar at room temperature, around 24 degrees.
```

`backend/tests/fixtures/vault/Rust Borrow Checker.md`:

```markdown
# Rust Borrow Checker

The borrow checker rejects code with two mutable references.
Lifetimes annotate how long references stay valid in Rust.
```

`backend/tests/fixtures/vault/Marathon Training.md`:

```markdown
# Marathon Training

Long run every Sunday, increasing weekly mileage ten percent.
Taper the final two weeks before the marathon race.
```

`backend/tests/fixtures/dataset.jsonl`:

```jsonl
{"question": "how often do I feed the sourdough starter?", "expected_sources": ["Sourdough Starter.md"]}
{"question": "why does the borrow checker reject mutable references?", "expected_sources": ["Rust Borrow Checker.md"]}
{"question": "note that does not exist anywhere", "expected_sources": ["Missing Note.md"]}
```

- [ ] **Step 2: Create the deterministic fake embedder**

`backend/tests/fakes.py`:

```python
"""Deterministic test doubles. No model downloads in CI."""
import hashlib

import numpy as np

DIM = 64


class BagOfWordsEmbedder:
    """Stand-in for SentenceTransformer: hashed, normalized bag-of-words.

    Texts sharing words get similar vectors, so ranking behaves sensibly
    and the e2e test can genuinely fail if retrieval wiring breaks.
    """

    def encode(self, texts):
        out = []
        for text in texts:
            vec = np.zeros(DIM, dtype=np.float32)
            for word in text.lower().split():
                h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
                vec[h % DIM] += 1.0
            norm = np.linalg.norm(vec)
            out.append(vec / norm if norm > 0 else vec)
        return np.array(out)
```

- [ ] **Step 3: Write the failing e2e test**

`backend/tests/test_eval_e2e.py`:

```python
import os

import chromadb
import pytest

import indexer
from eval.dataset import load_dataset
from eval.run_eval import run
from tests.fakes import BagOfWordsEmbedder

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


@pytest.fixture()
def indexed_collection(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", os.path.join(FIXTURES, "vault"))
    client = chromadb.EphemeralClient()
    collection = client.get_or_create_collection("eval_e2e")
    embedder = BagOfWordsEmbedder()
    summary = indexer.index_vault(collection, embedder, incremental=False, log=lambda *_: None)
    assert summary["chunks_written"] >= 3
    return collection, embedder


def test_eval_end_to_end_on_fixture_vault(indexed_collection):
    collection, embedder = indexed_collection
    cases = load_dataset(os.path.join(FIXTURES, "dataset.jsonl"))

    rows, summary = run(cases, model=embedder, collection=collection, k=4)

    by_q = {r["question"]: r for r in rows}
    assert by_q["how often do I feed the sourdough starter?"]["status"] == "hit"
    assert by_q["why does the borrow checker reject mutable references?"]["status"] == "hit"
    # Expected note absent from the index -> reported ungradable, not a miss.
    assert by_q["note that does not exist anywhere"]["status"] == "ungradable"

    assert summary["cases"] == 2
    assert summary["ungradable"] == 1
    assert summary["hit_rate"] == 1.0
    assert summary["mrr"] == 1.0
    assert summary["k"] == 4
```

Note: `from tests.fakes import ...` requires no `backend/tests/__init__.py`; pytest's rootdir handling plus the conftest sys.path insert makes both `tests.fakes` and plain modules importable. If `ModuleNotFoundError: tests` appears, add an empty `backend/tests/__init__.py` — Windows/Linux pytest versions differ here; either state is acceptable, tests passing is the gate.

- [ ] **Step 4: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_eval_e2e.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'eval.run_eval'`

- [ ] **Step 5: Implement run_eval.py**

`backend/eval/run_eval.py`:

```python
"""Score the current retrieval pipeline against the eval dataset.

Usage (from backend/, venv active):
    python -m eval.run_eval             # uses eval/dataset.jsonl
    python -m eval.run_eval --dataset path/to/other.jsonl --k 4

The dataset is private and gitignored; copy dataset.example.jsonl to
dataset.jsonl and replace it with real cases about your own vault.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import retrieval
from eval.dataset import load_dataset
from eval.scoring import aggregate, score_case, unique_sources

EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATASET = os.path.join(EVAL_DIR, "dataset.jsonl")
RESULTS_PATH = os.path.join(EVAL_DIR, "results.json")


def run(cases, *, model, collection, k=retrieval.TOP_K):
    """Score every case. Returns (per_case_rows, summary).

    A case whose expected sources are entirely absent from the index is
    "ungradable" (stale dataset entry) and excluded from the averages.
    """
    rows = []
    gradable = []
    for case in cases:
        expected = case["expected_sources"]
        present = collection.get(where={"source": {"$in": expected}}, include=[])
        if not (present.get("ids") or []):
            rows.append({"question": case["question"], "status": "ungradable",
                         "rank": None, "expected_sources": expected})
            continue

        candidates = retrieval.retrieve(
            case["question"], model=model, collection=collection,
            scope=case["scope"], k=k,
        )
        result = score_case(unique_sources(candidates), expected, k=k)
        gradable.append(result)
        rows.append({"question": case["question"],
                     "status": "hit" if result["hit"] else "miss",
                     "rank": result["rank"], "expected_sources": expected})

    summary = aggregate(gradable)
    summary["ungradable"] = sum(1 for r in rows if r["status"] == "ungradable")
    summary["k"] = k
    return rows, summary


def main():
    parser = argparse.ArgumentParser(description="Retrieval eval: hit-rate@k and MRR@k")
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--k", type=int, default=retrieval.TOP_K)
    args = parser.parse_args()

    if not os.path.exists(args.dataset):
        print(f"No dataset at {args.dataset}.")
        print(f"Copy {os.path.join(EVAL_DIR, 'dataset.example.jsonl')} to dataset.jsonl "
              "and replace it with real cases.")
        sys.exit(1)

    cases = load_dataset(args.dataset)

    # Heavy imports deferred so `import eval.run_eval` stays cheap in tests.
    import chromadb
    from sentence_transformers import SentenceTransformer

    import config
    collection = chromadb.PersistentClient(path=config.get_chroma_path()).get_collection("second_brain")
    model = SentenceTransformer("all-MiniLM-L6-v2")  # must match main.py's embedder

    rows, summary = run(cases, model=model, collection=collection, k=args.k)

    for row in rows:
        mark = {"hit": "HIT ", "miss": "MISS", "ungradable": "N/A "}[row["status"]]
        rank = f"@{row['rank']}" if row["rank"] else "   "
        print(f"{mark} {rank:>3}  {row['question'][:70]}")
    print()
    print(f"cases: {summary['cases']} gradable, {summary['ungradable']} ungradable")
    print(f"hit-rate@{summary['k']}: {summary['hit_rate']:.1%}")
    print(f"MRR@{summary['k']}: {summary['mrr']:.3f}")

    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "cases": rows}, f, indent=2)
    print(f"\nWrote {RESULTS_PATH}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest backend/tests -q`
Expected: all passed (scoring + dataset + retrieval + e2e).

- [ ] **Step 7: Commit**

```bash
git add backend/eval/run_eval.py backend/tests/fakes.py backend/tests/fixtures backend/tests/test_eval_e2e.py
git commit -m "Add eval runner CLI with fixture-vault end-to-end test"
```

---

### Task 5: CI, gitignore, README section

**Files:**
- Create: `backend/requirements-dev.txt`
- Modify: `.github/workflows/ci.yml` (python-check job)
- Modify: `.gitignore` (project-specific section at the end)
- Modify: `README.md` (new section after "What it includes"; Validation section)

**Interfaces:**
- Consumes: the full test suite (Tasks 1–4).
- Produces: green CI running pytest; README "Retrieval quality" section whose table row Task 6 fills in.

- [ ] **Step 1: Add dev requirements**

`backend/requirements-dev.txt`:

```
-r requirements.txt
pytest==8.4.2
```

- [ ] **Step 2: Extend the CI python-check job**

In `.github/workflows/ci.yml`, replace the `Install Python Dependencies` and `Python Syntax Verification` steps of the `python-check` job with:

```yaml
      - name: Install Python Dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r backend/requirements-dev.txt

      - name: Python Syntax Verification
        run: python -m py_compile backend/main.py backend/rag_query.py backend/retrieval.py backend/eval/dataset.py backend/eval/scoring.py backend/eval/run_eval.py

      - name: Backend Tests
        run: python -m pytest backend/tests -q
```

- [ ] **Step 3: Gitignore the private dataset and local results**

Append to the `# Project specific` section of `.gitignore`:

```
# Retrieval eval: private dataset + local results stay off GitHub
backend/eval/dataset.jsonl
backend/eval/results.json
```

- [ ] **Step 4: Add the README section**

In `README.md`, insert after the "What it includes" section:

````markdown
## Retrieval quality

Retrieval is scored against a private set of real questions about my own
vault: each case asks whether the note that actually answers the question
shows up in the top 4 chunks handed to Qwen. The harness is public
(`backend/eval/`); the dataset stays local because it's my personal notes.

| Change | hit-rate@4 | MRR@4 |
|---|---|---|
| Baseline: MiniLM embeddings, 500-word chunks, vector-only | _measuring_ | _measuring_ |

Score it against your own vault:

```bash
cd backend
cp eval/dataset.example.jsonl eval/dataset.jsonl   # then write real cases
python -m eval.run_eval
```
````

Also extend the README "Validation" section's Python block with:

```bash
python -m pytest backend/tests -q
```

The `_measuring_` cells are filled with real numbers in Task 6 before the PR opens — the PR must not merge with placeholder cells.

- [ ] **Step 5: Verify CI config locally**

Run: `python -m pytest backend/tests -q` — Expected: all passed.
Run: `python -m py_compile backend/main.py backend/rag_query.py backend/retrieval.py backend/eval/dataset.py backend/eval/scoring.py backend/eval/run_eval.py` — Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add backend/requirements-dev.txt .github/workflows/ci.yml .gitignore README.md
git commit -m "Wire eval + tests into CI and document retrieval quality in README"
```

---

### Task 6: Author the real dataset, run the baseline, fill the README (Bryan-in-the-loop)

**Files:**
- Create: `backend/eval/dataset.jsonl` (gitignored — never committed)
- Modify: `README.md` (baseline table row)

**Interfaces:**
- Consumes: `python -m eval.run_eval` (Task 4), README table (Task 5).
- Produces: real baseline hit-rate@4 and MRR@4 numbers in README and for the PR description.

- [ ] **Step 1: Draft candidate questions for Bryan**

Scan the vault's note titles and recent notes (read-only) and draft ~40 candidate cases in the dataset format, mixing: exact-token questions (project names, config values), paraphrase questions (no shared words with the note title), and `"scope": "chats"` questions against `05 AI Chats/`. Save the draft to `backend/eval/dataset.jsonl`.

- [ ] **Step 2: Bryan reviews the dataset** *(his hands)*

Bryan edits/approves the ~40 cases — only he knows which note truly answers which question. Gate: do not proceed until he confirms.

- [ ] **Step 3: Run the baseline eval**

Run (backend venv): `python -m eval.run_eval`
Expected: per-case table, then summary lines with hit-rate@4 and MRR@4. If any case is ungradable, fix its path in `dataset.jsonl` (find the real path with the vault search or `collection.get`) and re-run until ungradable = 0.

- [ ] **Step 4: Fill the README table row**

Replace the `_measuring_` cells with the real numbers, e.g. `| Baseline: ... | 62% | 0.48 |`.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "Record baseline retrieval quality: hit-rate@4 and MRR@4"
```

---

### Task 7: Push and open PR

**Files:** none (git/GitHub only)

- [ ] **Step 1: Full local validation**

```bash
python -m pytest backend/tests -q
python -m py_compile backend/main.py backend/rag_query.py backend/retrieval.py backend/eval/dataset.py backend/eval/scoring.py backend/eval/run_eval.py
cd frontend && npm run build && cd ..
```

Expected: all pass (frontend build unchanged but verified — source-level green is not shipped green).

- [ ] **Step 2: Push and open the PR**

```bash
git push -u origin rag-eval-improvements
gh pr create --title "Retrieval eval harness + baseline" --body "..."
```

PR body must include: why (make retrieval measurable before improving it), what (shared retrieval module, eval harness, CI fixture test), the baseline numbers from Task 6, the privacy note (dataset gitignored, example committed), and the follow-up plan (PRs 2–5 per the spec).

- [ ] **Step 3: Wait for CI green, then hand to Bryan for merge**

Check: `gh pr checks` — all green. Bryan merges; PRs 2–5 get planned against the merged baseline.
