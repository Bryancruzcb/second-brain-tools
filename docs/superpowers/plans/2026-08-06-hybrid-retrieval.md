# Hybrid Retrieval: BM25 + RRF (PR 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a keyword leg (BM25) beside vector search and fuse them with Reciprocal Rank Fusion, targeting the exact-token misses that keep hit-rate@4 at 70%. Batch the small chunker cleanups carried from PR 2's reviews.

**Architecture:** New `backend/lexical.py` holds an in-memory BM25 index built from the same Chroma collection the vector leg uses (rebuilt at backend startup and after each ingestion). `backend/retrieval.py` gains `rrf_fuse()` and `retrieve_hybrid()` — vector top-20 + BM25 top-20 → RRF (k=60) → top-k. Both endpoints and the eval switch to `retrieve_hybrid`, degrading to vector-only when the lexical index is unavailable.

**Tech Stack:** `rank_bm25` (pure Python, new runtime dep), existing pytest suite (36 tests).

**Scope:** PR 3 of `docs/superpowers/specs/2026-08-05-rag-eval-improvements-design.md`. Numbers to beat: hit-rate@4 70.0%, MRR@4 0.529.

## Global Constraints

- No cloud calls. Branch: `rag-hybrid-retrieval` (already created).
- The eval must keep measuring the app's true path: endpoints and eval both go through `retrieve_hybrid`.
- BM25 unavailability (build failure, empty index, still loading) degrades to vector-only with a logged warning — never a crash, never a silent behavior fork in the candidates' shape.
- `/api/query` and `/api/search` response shapes unchanged. Lexical candidates carry `score`, not `distance` — endpoint formatting must use `.get("distance", 0.0)`.
- Fusion constants: `HYBRID_DEPTH = 20` per leg, `RRF_K = 60`, final `k` unchanged (4 for query/eval, 6 for search).
- Merge gate: regression doesn't merge; neutral needs plainly-stated numbers + qualitative win.
- Private dataset stays gitignored. Full local reindex before the eval re-run (chunker indent fixes can shift chunk boundaries).

---

### Task 1: Chunker cleanups (carried from PR 2 reviews)

**Files:**
- Modify: `backend/indexer.py` (HEADING_RE, FENCE_RE, fence-close condition in `split_sections`)
- Modify: `backend/tests/test_chunker.py` (import line + 4 new tests)

**Interfaces:** unchanged signatures; behavior refinements only: (a) headings and fences may be indented 0-3 spaces (CommonMark); 4+ spaces = indented code block, neither splits nor toggles fence state; (b) a closing fence must carry no info string (` ```python ` inside a ``` block no longer closes it).

- [ ] **Step 1: Write the failing tests**

In `backend/tests/test_chunker.py`, change the import line to drop the unused constant:

```python
from indexer import chunk_text, split_sections
```

Append:

```python
def test_indented_heading_up_to_three_spaces_splits():
    doc = "intro\n   # Indented\nbody\n"
    assert [s["heading"] for s in split_sections(doc)] == ["", "Indented"]


def test_four_space_indented_hash_is_code_not_heading():
    doc = "# Real\n    # code comment\nbody\n"
    assert len(split_sections(doc)) == 1


def test_four_space_indented_fence_marker_is_not_a_fence():
    doc = "# Real\n    ```\n# Actual\nbody\n"
    assert [s["heading"] for s in split_sections(doc)] == ["Real", "Actual"]


def test_closing_fence_with_info_string_does_not_close():
    doc = "# Real\n```\n```python\n# still code\n```\n\n# After\nx\n"
    assert [s["heading"] for s in split_sections(doc)] == ["Real", "After"]
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `backend/venv/Scripts/python.exe -m pytest backend/tests/test_chunker.py -v`
Expected: 3-4 of the new tests FAIL against current behavior (`test_four_space_indented_hash...` may already pass; the indented-heading, indented-fence, and info-string-close tests must fail).

- [ ] **Step 3: Implement**

In `backend/indexer.py`:

```python
HEADING_RE = re.compile(r"^ {0,3}(#{1,6})\s+(.*)$")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*(.*)$")
```

In `split_sections`, replace the fence-detection block so it matches the RAW line (no lstrip — 4+-space indentation is an indented code block per CommonMark) and rejects info-string closers:

```python
        m_fence = FENCE_RE.match(line)
        if m_fence:
            marker = m_fence.group(1)
            info = m_fence.group(2).strip()
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and not info:
                # CommonMark: a closing fence matches the opening char, is at
                # least as long, and carries no info string. An unclosed
                # fence runs to end of file (also per CommonMark).
                fence = None
            lines.append(line)
            continue
```

`HEADING_RE` already runs on the raw line, so the `{0,3}` prefix change covers indented headings with no other edits.

- [ ] **Step 4: Run the chunker tests, then the full suite**

Run: `backend/venv/Scripts/python.exe -m pytest backend/tests/test_chunker.py -v` → 16 passed
Run: `backend/venv/Scripts/python.exe -m pytest backend/tests -q` → 40 passed

- [ ] **Step 5: Commit**

```bash
git add backend/indexer.py backend/tests/test_chunker.py
git commit -m "Align heading and fence detection with CommonMark indentation rules"
```

---

### Task 2: Lexical BM25 index

**Files:**
- Modify: `backend/requirements.txt` (add `rank_bm25==0.2.2` after `chromadb`)
- Create: `backend/lexical.py`
- Test: `backend/tests/test_lexical.py`

**Interfaces:**
- Produces: `lexical.tokenize(text) -> list[str]` (lowercase `[a-z0-9_]+` tokens); `LexicalIndex.build(collection)` classmethod reading the whole collection via `collection.get(include=["documents", "metadatas"])`; `len(index)` = chunk count; `index.search(query_text, scope="notes", k=10) -> list[dict]` best-first candidates `{"id", "source", "title", "chunk", "score"}` (score float, higher better), scope-filtered like `retrieval.scope_filter`, zero-score results excluded, empty query/corpus → `[]`.

- [ ] **Step 0: Install the dependency**

Add `rank_bm25==0.2.2` to `backend/requirements.txt` (line after `chromadb==1.5.9`), then:
`backend/venv/Scripts/python.exe -m pip install rank_bm25==0.2.2`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_lexical.py`:

```python
from lexical import LexicalIndex, tokenize


class FakeGetCollection:
    def __init__(self, ids, docs, metas):
        self._payload = {"ids": ids, "documents": docs, "metadatas": metas}

    def get(self, include=None):
        return self._payload


def build_index():
    return LexicalIndex.build(FakeGetCollection(
        ids=["a_chunk_0", "b_chunk_0", "c_chunk_0"],
        docs=[
            "sourdough starter feeding schedule flour water",
            "rust borrow checker lifetime CHUNK_SIZE mutable",
            "marathon training taper mileage sunday",
        ],
        metas=[
            {"source": "a.md", "title": "Sourdough", "category": "note"},
            {"source": "b.md", "title": "Rust", "category": "chat"},
            {"source": "c.md", "title": "Marathon", "category": "note"},
        ],
    ))


def test_tokenize_keeps_snake_case_and_lowers():
    assert tokenize("Set CHUNK_SIZE=500, ok?") == ["set", "chunk_size", "500", "ok"]


def test_exact_token_ranks_right_chunk_first():
    index = build_index()
    out = index.search("chunk_size", scope="all", k=3)
    assert out[0]["source"] == "b.md"
    assert out[0]["id"] == "b_chunk_0"
    assert out[0]["score"] > 0


def test_scope_filter_notes_excludes_chats():
    index = build_index()
    sources = [c["source"] for c in index.search("sourdough rust marathon", scope="notes", k=5)]
    assert "b.md" not in sources
    assert set(sources) <= {"a.md", "c.md"}


def test_scope_filter_chats_only():
    index = build_index()
    sources = [c["source"] for c in index.search("rust borrow", scope="chats", k=5)]
    assert sources == ["b.md"]


def test_no_overlap_returns_empty():
    index = build_index()
    assert index.search("zzz qqq", scope="all", k=3) == []


def test_empty_corpus_and_empty_query():
    empty = LexicalIndex.build(FakeGetCollection([], [], []))
    assert len(empty) == 0
    assert empty.search("anything") == []
    index = build_index()
    assert index.search("   ") == []
```

- [ ] **Step 2: Run to verify failure**

Run: `backend/venv/Scripts/python.exe -m pytest backend/tests/test_lexical.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lexical'`

- [ ] **Step 3: Implement `backend/lexical.py`**

```python
"""In-memory BM25 index over the Chroma chunk corpus.

Built from the same collection the vector leg searches, so both retrieval
legs see identical chunks. Pure Python (rank_bm25), rebuilt at backend
startup and after each ingestion run; goes stale if another process
updates the index until the next rebuild or restart. A build failure
downgrades hybrid retrieval to vector-only — never a crash.
"""
import re

from rank_bm25 import BM25Okapi

TOKEN_RE = re.compile(r"[a-z0-9_]+")


def tokenize(text):
    """Lowercase alphanumeric/underscore tokens; snake_case stays whole."""
    return TOKEN_RE.findall(text.lower())


class LexicalIndex:
    """BM25 over every chunk in the collection, with scope filtering."""

    def __init__(self, entries, bm25):
        self._entries = entries
        self._bm25 = bm25

    @classmethod
    def build(cls, collection):
        got = collection.get(include=["documents", "metadatas"])
        ids = got.get("ids") or []
        docs = got.get("documents") or []
        metas = got.get("metadatas") or []
        entries, corpus = [], []
        for chunk_id, doc, meta in zip(ids, docs, metas):
            meta = meta or {}
            entries.append({
                "id": chunk_id,
                "source": meta.get("source", ""),
                "title": meta.get("title", "Untitled Note"),
                "chunk": doc,
                "category": meta.get("category", "note"),
            })
            corpus.append(tokenize(doc))
        if not entries:
            return cls([], None)
        return cls(entries, BM25Okapi(corpus))

    def __len__(self):
        return len(self._entries)

    def search(self, query_text, scope="notes", k=10):
        """Top-k chunks by BM25 score, best first, honoring the scope filter.

        Candidate shape matches retrieval.retrieve() but carries "score"
        (higher better) instead of "distance". Zero-score chunks (no token
        overlap) are excluded — BM25 has nothing to say about them.
        """
        if self._bm25 is None:
            return []
        tokens = tokenize(query_text)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        out = []
        for i in ranked:
            if scores[i] <= 0:
                break
            entry = self._entries[i]
            if scope == "chats" and entry["category"] != "chat":
                continue
            if scope == "notes" and entry["category"] == "chat":
                continue
            out.append({
                "id": entry["id"],
                "source": entry["source"],
                "title": entry["title"],
                "chunk": entry["chunk"],
                "score": float(scores[i]),
            })
            if len(out) >= k:
                break
        return out
```

- [ ] **Step 4: Run tests**

Run: `backend/venv/Scripts/python.exe -m pytest backend/tests/test_lexical.py -v` → 6 passed
Run: `backend/venv/Scripts/python.exe -m pytest backend/tests -q` → 46 passed

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/lexical.py backend/tests/test_lexical.py
git commit -m "Add in-memory BM25 lexical index over the chunk corpus"
```

---

### Task 3: RRF fusion + retrieve_hybrid

**Files:**
- Modify: `backend/retrieval.py` (candidates gain `id`; add `HYBRID_DEPTH`, `RRF_K`, `rrf_fuse`, `retrieve_hybrid`)
- Modify: `backend/tests/test_retrieval.py` (CANNED gains ids; expected dicts gain `id`; new fusion/hybrid tests)

**Interfaces:**
- `retrieve()` candidates gain `"id"` (from Chroma's `ids`; `""` fallback when a fake omits them). Existing keys unchanged.
- `rrf_fuse(ranked_lists, k=TOP_K, rrf_k=RRF_K) -> list[dict]` — fuses best-first lists by chunk identity (`id` when non-empty, else `(source, chunk)`), score = Σ 1/(rrf_k + rank), ties broken by first insertion (vector list first).
- `retrieve_hybrid(query_text, *, model, collection, lexical=None, scope="notes", k=TOP_K)` — vector top-HYBRID_DEPTH; if `lexical` is None or empty → vector top-k (fallback); else fuse with `lexical.search(query_text, scope, HYBRID_DEPTH)`.

- [ ] **Step 1: Update existing tests + write new failing tests**

In `backend/tests/test_retrieval.py`: add `"ids": [["id_a", "id_b"]]` to `CANNED`, and `"id": "id_a"` / `"id": "id_b"` to the two expected dicts in `test_retrieve_parses_chroma_results_into_candidates`. Then append:

```python
def test_retrieve_tolerates_missing_ids_key():
    coll = FakeCollection({
        "documents": [["text"]],
        "metadatas": [[{"source": "a.md", "title": "A"}]],
        "distances": [[0.2]],
    })
    out = retrieval.retrieve("q", model=FakeModel(), collection=coll)
    assert out[0]["id"] == ""


def _cand(cid, source="s.md"):
    return {"id": cid, "source": source, "title": "T", "chunk": f"chunk {cid}", "distance": 0.1}


def test_rrf_item_in_both_lists_wins():
    a, b, c = _cand("a"), _cand("b"), _cand("c")
    fused = retrieval.rrf_fuse([[a, b], [c, a]], k=3)
    assert fused[0]["id"] == "a"  # 1/(60+1) + 1/(60+2) beats any single entry


def test_rrf_scores_by_rank_position():
    a, b = _cand("a"), _cand("b")
    fused = retrieval.rrf_fuse([[a, b], [b, a]], k=2)
    # both sum to 1/61 + 1/62 — tie; first-inserted (a, from list one) wins
    assert [c["id"] for c in fused] == ["a", "b"]


def test_rrf_truncates_to_k():
    lst = [_cand(str(i)) for i in range(6)]
    assert len(retrieval.rrf_fuse([lst], k=4)) == 4


def test_rrf_falls_back_to_source_chunk_identity_when_id_empty():
    x1 = {"id": "", "source": "x.md", "title": "X", "chunk": "same text", "distance": 0.1}
    x2 = {"id": "", "source": "x.md", "title": "X", "chunk": "same text", "score": 2.0}
    fused = retrieval.rrf_fuse([[x1], [x2]], k=2)
    assert len(fused) == 1  # same chunk, fused despite different score keys


class FakeLexical:
    def __init__(self, results):
        self.results = results
        self.last_args = None

    def __len__(self):
        return len(self.results)

    def search(self, query_text, scope="notes", k=10):
        self.last_args = (query_text, scope, k)
        return self.results[:k]


def test_hybrid_falls_back_to_vector_only_without_lexical():
    coll = FakeCollection(CANNED)
    out = retrieval.retrieve_hybrid("q", model=FakeModel(), collection=coll, lexical=None, k=2)
    assert [c["id"] for c in out] == ["id_a", "id_b"]
    assert coll.last_kwargs["n_results"] == retrieval.HYBRID_DEPTH


def test_hybrid_fuses_vector_and_lexical():
    coll = FakeCollection(CANNED)
    lex = FakeLexical([_cand("id_b"), _cand("id_z")])
    out = retrieval.retrieve_hybrid("q", model=FakeModel(), collection=coll, lexical=lex, scope="chats", k=2)
    assert out[0]["id"] == "id_b"  # in both lists
    assert lex.last_args == ("q", "chats", retrieval.HYBRID_DEPTH)
```

- [ ] **Step 2: Run to verify failure**

Run: `backend/venv/Scripts/python.exe -m pytest backend/tests/test_retrieval.py -v`
Expected: existing parse test fails on missing `id` key; new tests fail on missing `rrf_fuse`/`retrieve_hybrid`.

- [ ] **Step 3: Implement in `backend/retrieval.py`**

Add constants under `TOP_K`:

```python
HYBRID_DEPTH = 20
RRF_K = 60
```

In `retrieve()`, capture ids and add to each candidate:

```python
        docs = results["documents"][0]
        metas = results["metadatas"][0]
        dists = (results.get("distances") or [[0.0] * len(docs)])[0]
        ids = (results.get("ids") or [[""] * len(docs)])[0]
        for doc, meta, dist, chunk_id in zip(docs, metas, dists, ids):
            meta = meta or {}
            candidates.append({
                "id": chunk_id,
                "source": meta.get("source", ""),
                "title": meta.get("title", "Untitled Note"),
                "chunk": doc,
                "distance": float(dist),
            })
```

Append:

```python
def rrf_fuse(ranked_lists, k=TOP_K, rrf_k=RRF_K):
    """Reciprocal Rank Fusion over best-first candidate lists.

    Fuses by chunk identity — "id" when non-empty, else (source, chunk).
    An item appearing in several lists sums 1/(rrf_k + rank) across them,
    which rewards agreement without needing comparable scores. Ties break
    by first insertion, i.e. the earlier list's ordering.
    """
    scores = {}
    first_seen = {}
    for lst in ranked_lists:
        for rank, cand in enumerate(lst, start=1):
            key = cand.get("id") or (cand["source"], cand["chunk"])
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
            if key not in first_seen:
                first_seen[key] = cand
    ranked = sorted(scores, key=scores.get, reverse=True)
    return [first_seen[key] for key in ranked[:k]]


def retrieve_hybrid(query_text, *, model, collection, lexical=None, scope="notes", k=TOP_K):
    """Vector + BM25 retrieval fused with RRF.

    Falls back to plain vector retrieval when no lexical index is
    available (still building, build failed, or empty collection) so the
    endpoints never crash on a missing keyword leg.
    """
    vector = retrieve(query_text, model=model, collection=collection,
                      scope=scope, k=HYBRID_DEPTH)
    if lexical is None or len(lexical) == 0:
        return vector[:k]
    keyword = lexical.search(query_text, scope=scope, k=HYBRID_DEPTH)
    return rrf_fuse([vector, keyword], k=k)
```

- [ ] **Step 4: Run tests**

Run: `backend/venv/Scripts/python.exe -m pytest backend/tests/test_retrieval.py -v` → 12 passed
Run: `backend/venv/Scripts/python.exe -m pytest backend/tests -q` → 53 passed

- [ ] **Step 5: Commit**

```bash
git add backend/retrieval.py backend/tests/test_retrieval.py
git commit -m "Add RRF fusion and hybrid retrieval with vector-only fallback"
```

---

### Task 4: Wire hybrid into the app and the eval

**Files:**
- Modify: `backend/main.py` (global + import, lifespan build, ingestion rebuild hook, both endpoints, `.get("distance", 0.0)` in run_query formatting)
- Modify: `backend/eval/run_eval.py` (`run()` gains `lexical=None` param; `main()` builds the index)
- Modify: `backend/tests/test_eval_e2e.py` (hybrid path + 2 new fixture notes + miss case)
- Modify: `backend/tests/test_search_endpoint.py` (monkeypatch `main.lexical_index = None` so the fallback path is pinned; one new test with a FakeLexical)
- Create: `backend/tests/fixtures/vault/Coffee Brewing.md`, `backend/tests/fixtures/vault/Garden Compost.md`
- Modify: `backend/tests/fixtures/dataset.jsonl` (add the miss case)

**Interfaces:**
- `main.lexical_index` global (None until built); `_build_lexical_background()` builds it and is called from lifespan (background thread) and at the end of `run_ingestion_sync`.
- `run_eval.run(cases, *, model, collection, lexical=None, k)` — retrieval goes through `retrieval.retrieve_hybrid(..., lexical=lexical)`.

- [ ] **Step 1: main.py wiring**

Add `import lexical` after `import retrieval`. Add global `lexical_index = None` near `model = None`. Add:

```python
def _build_lexical_background():
    """(Re)build the BM25 index; on failure hybrid degrades to vector-only."""
    global lexical_index
    if chroma_collection is None:
        return
    try:
        lexical_index = lexical.LexicalIndex.build(chroma_collection)
        logger.info("BM25 lexical index built over %d chunks.", len(lexical_index))
    except Exception as e:
        logger.error(f"Failed to build BM25 index (hybrid degrades to vector-only): {e}")
```

In `lifespan`, after the model-load task: `asyncio.create_task(asyncio.to_thread(_build_lexical_background))`.
At the end of `run_ingestion_sync` (after the completion log): `_build_lexical_background()`.
In `run_query`: `retrieval.retrieve(...)` → `retrieval.retrieve_hybrid(..., lexical=lexical_index, ...)`; in the sources loop use `"distance": c.get("distance", 0.0)`.
In `search_notes`: same substitution with `lexical=lexical_index, k=6` (keep the shape code unchanged).

- [ ] **Step 2: run_eval.py**

`run()` signature: `def run(cases, *, model, collection, lexical=None, k=retrieval.TOP_K):` and the retrieval call becomes `retrieval.retrieve_hybrid(case["question"], model=model, collection=collection, lexical=lexical, scope=case["scope"], k=k)`. In `main()`, after building the collection/model: `from lexical import LexicalIndex` (with the deferred imports) and `lex = LexicalIndex.build(collection)`, passed as `lexical=lex`.

- [ ] **Step 3: Fixtures + e2e**

`backend/tests/fixtures/vault/Coffee Brewing.md`:

```markdown
# Coffee Brewing

Grind beans fresh each morning, medium coarse for the press.

## Grinder Settings

Eighteen clicks on the hand grinder, thirty grams per brew.
```

`backend/tests/fixtures/vault/Garden Compost.md`:

```markdown
# Garden Compost

Turn the compost pile weekly and keep it damp, adding greens and browns in balance.
```

Append to `backend/tests/fixtures/dataset.jsonl` (the question deliberately shares zero tokens with its expected note and strong tokens with the other notes — a synthetic case that forces the expected note out of the top 4 so the "miss" path finally executes):

```jsonl
{"question": "sourdough starter borrow checker marathon taper coffee grinder", "expected_sources": ["Garden Compost.md"]}
```

In `backend/tests/test_eval_e2e.py`: build the lexical index inside the fixture and thread it through:

```python
from lexical import LexicalIndex
```

In `indexed_collection`, after `index_vault`: change the guard to `assert summary["chunks_written"] >= 5`, add `lex = LexicalIndex.build(collection)`, and return `collection, embedder, lex`. Update both existing tests' unpacking (`collection, embedder, lex = indexed_collection`) and the `run(...)` call to pass `lexical=lex`. New/updated assertions in `test_eval_end_to_end_on_fixture_vault`:

```python
    assert by_q["sourdough starter borrow checker marathon taper coffee grinder"]["status"] == "miss"
    assert by_q["sourdough starter borrow checker marathon taper coffee grinder"]["rank"] is None

    assert summary["cases"] == 3
    assert summary["ungradable"] == 1
    assert summary["hit_rate"] == 2 / 3
    assert summary["mrr"] == (1.0 + 1.0 + 0.0) / 3
```

(The two original hit cases must still rank #1 — their token overlap dominates; if the new notes disturb that, adjust the new notes' wording, not the assertions.)

- [ ] **Step 4: Search endpoint tests**

In `backend/tests/test_search_endpoint.py`, add `monkeypatch.setattr(main, "lexical_index", None)` to both existing tests (pins the documented fallback path), add `import retrieval` to the imports, and update the existing assertion `coll.last_kwargs["n_results"] == 6` to `coll.last_kwargs["n_results"] == retrieval.HYBRID_DEPTH` — the vector leg now over-retrieves to fusion depth and truncates to 6 afterward, so the kwarg legitimately changes while the response stays identical. Then append:

```python
def test_search_uses_lexical_leg_when_available(monkeypatch):
    from tests.test_retrieval import FakeLexical
    coll = FakeCollection(CANNED)
    lex = FakeLexical([
        {"id": "id_l", "source": "l.md", "title": "Lex", "chunk": "lexical hit", "score": 3.0},
    ])
    monkeypatch.setattr(main, "model", FakeModel())
    monkeypatch.setattr(main, "chroma_collection", coll)
    monkeypatch.setattr(main, "lexical_index", lex)
    client = TestClient(main.app)
    titles = [r["title"] for r in client.get("/api/search", params={"q": "x"}).json()["results"]]
    assert "Lex" in titles
    assert lex.last_args[2] == 20  # HYBRID_DEPTH reaches the lexical leg
```

(`FakeLexical` lives in test_retrieval.py from Task 3 — import it rather than duplicating. CANNED in this file needs `"ids": [["id_a", "id_a2", "id_b"]]` added so fused candidates keep stable identity; the existing expected results are unchanged because response projection doesn't read `id`.)

- [ ] **Step 5: Run everything**

Run: `backend/venv/Scripts/python.exe -m pytest backend/tests -q` → 54 passed
Run: `backend/venv/Scripts/python.exe -m py_compile backend/main.py backend/eval/run_eval.py backend/lexical.py backend/retrieval.py` → exit 0

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/eval/run_eval.py backend/tests/test_eval_e2e.py backend/tests/test_search_endpoint.py backend/tests/fixtures
git commit -m "Serve /api/query, /api/search, and the eval through hybrid retrieval"
```

---

### Task 5: Reindex, measure, record (controller-run)

- [ ] **Step 1:** Full reindex (chunker indent fixes can shift boundaries): from `backend/`, `venv/Scripts/python.exe scripts/rebuild_rag_index.py --full`.
- [ ] **Step 2:** `venv/Scripts/python.exe -m eval.run_eval` — record hit-rate@4 / MRR@4. Merge gate per Global Constraints.
- [ ] **Step 3:** README: new table row `| + Hybrid retrieval (BM25 keyword leg + reciprocal rank fusion) | X% | 0.XX |`; update the top-of-README locality sentence from "retrieval is local ChromaDB" to "retrieval is local ChromaDB plus an in-memory BM25 index".
- [ ] **Step 4:** Commit: `Record hybrid retrieval numbers`.

---

### Task 6: Final review, push, PR

- [ ] **Step 1:** Whole-branch review (merge-base..HEAD package) on the most capable model; fix Important+ findings before push.
- [ ] **Step 2:** Full validation: suite green, py_compile, `cd frontend && npm run build`.
- [ ] **Step 3:** Push `rag-hybrid-retrieval`, `gh pr create` — body: why (exact-token misses), what, before/after table (three rows now), rank_bm25 dep note, staleness note (BM25 rebuilt at startup + after Re-index; external-process index updates need a backend restart), reindex-after-merge note.
- [ ] **Step 4:** Watch CI to green; hand to Bryan for merge.
