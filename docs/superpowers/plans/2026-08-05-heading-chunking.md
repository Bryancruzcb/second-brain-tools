# Heading-Aware Chunking (PR 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the blind 500-word chunker with markdown-heading-aware chunking (measured before/after on the retrieval eval), and fold `/api/search` onto the shared `retrieval.retrieve()` path.

**Architecture:** `indexer.chunk_text()` becomes heading-aware: split into sections at ATX headings (code-fence aware), greedily merge small adjacent sections up to the word cap, fall back to the word window inside oversized sections. Chunks become `{"text", "heading"}` dicts and chunk metadata gains a `heading` field. `/api/search` drops its inline Chroma query and calls `retrieve(..., k=6)`.

**Tech Stack:** Python 3.10+, existing pytest suite (21 tests), ChromaDB, FastAPI TestClient for the endpoint test.

**Scope:** PR 2 of `docs/superpowers/specs/2026-08-05-rag-eval-improvements-design.md`. Baseline to beat (recorded in README): hit-rate@4 70.0%, MRR@4 0.496 over the private 40-case dataset.

## Global Constraints

- No cloud calls; everything local. Branch: `rag-heading-chunking` (already created).
- `CHUNK_SIZE = 500` words and `CHUNK_OVERLAP = 50` stay as the cap/overlap constants.
- The eval numbers decide the merge: a regression doesn't merge; neutral merges only with the flat numbers stated plainly (README register is honest).
- `/api/search` response shape must not change: `{"results": [{"title", "id", "snippet"}]}`, title-deduped, snippet 150 chars, k=6.
- The private dataset stays gitignored; PR description carries before/after numbers.
- Requires a full local reindex before the eval re-run (`backend/scripts/rebuild_rag_index.py --full`).

---

### Task 1: Heading-aware chunker (pure functions)

**Files:**
- Modify: `backend/indexer.py:119-126` (replace `chunk_text`, add `split_sections` above it)
- Test: `backend/tests/test_chunker.py` (new)

**Interfaces:**
- Consumes: nothing new.
- Produces: `split_sections(text: str) -> list[dict]` — `{"heading": str, "text": str}` per section, heading line included in its section's text, preamble (content before the first heading, including YAML frontmatter) gets `heading=""`; ATX headings only (`#` … `######`), heading-looking lines inside ``` / ~~~ fences do NOT split. `chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP) -> list[dict]` — `{"text": str, "heading": str}` chunks: consecutive sections merge while total words ≤ chunk_size (merged chunk keeps the FIRST merged section's heading); a single section over chunk_size falls back to the word window with overlap, every windowed piece keeping that section's heading; empty/whitespace input → `[]`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_chunker.py`:

```python
from indexer import CHUNK_SIZE, chunk_text, split_sections


# ── split_sections ──────────────────────────────────────────────────────────

def test_splits_at_atx_headings_with_preamble():
    doc = "intro line\n\n# Alpha\nalpha body\n\n## Beta\nbeta body\n"
    sections = split_sections(doc)
    assert [s["heading"] for s in sections] == ["", "Alpha", "Beta"]
    assert sections[0]["text"].strip() == "intro line"
    assert sections[1]["text"].startswith("# Alpha")
    assert "alpha body" in sections[1]["text"]


def test_heading_inside_code_fence_does_not_split():
    doc = "# Real\nbefore\n```\n# not a heading\nstill code\n```\nafter\n"
    sections = split_sections(doc)
    assert len(sections) == 1
    assert "# not a heading" in sections[0]["text"]


def test_tilde_fence_also_respected():
    doc = "# Real\n~~~\n## fenced\n~~~\ntail\n"
    assert len(split_sections(doc)) == 1


def test_heading_only_document():
    sections = split_sections("# Lonely\n")
    assert len(sections) == 1
    assert sections[0]["heading"] == "Lonely"


def test_empty_document():
    assert split_sections("") == []
    assert split_sections("   \n  \n") == []


# ── chunk_text ──────────────────────────────────────────────────────────────

def test_small_sections_merge_into_one_chunk():
    doc = "# A\nshort a\n\n# B\nshort b\n"
    chunks = chunk_text(doc)
    assert len(chunks) == 1
    assert chunks[0]["heading"] == "A"
    assert "short a" in chunks[0]["text"] and "short b" in chunks[0]["text"]


def test_sections_split_when_cap_would_be_exceeded():
    a = "# A\n" + " ".join(["alpha"] * 300)
    b = "# B\n" + " ".join(["beta"] * 300)
    chunks = chunk_text(a + "\n" + b + "\n")
    assert len(chunks) == 2
    assert chunks[0]["heading"] == "A"
    assert chunks[1]["heading"] == "B"
    assert "beta" not in chunks[0]["text"]


def test_oversized_section_falls_back_to_word_window():
    doc = "# Big\n" + " ".join(f"w{i}" for i in range(1200))
    chunks = chunk_text(doc)
    # step = 500 - 50 = 450 -> windows at 0, 450, 900
    assert len(chunks) == 3
    assert all(c["heading"] == "Big" for c in chunks)
    first_words = chunks[0]["text"].split()
    second_words = chunks[1]["text"].split()
    assert first_words[-50:] == second_words[:50]  # overlap preserved


def test_preamble_only_note_gets_empty_heading():
    chunks = chunk_text("just plain text with no headings\n")
    assert len(chunks) == 1
    assert chunks[0]["heading"] == ""


def test_empty_input_yields_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("  \n \n") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run (repo root): `backend/venv/Scripts/python.exe -m pytest backend/tests/test_chunker.py -v`
Expected: FAIL with `ImportError: cannot import name 'split_sections' from 'indexer'`

- [ ] **Step 3: Implement**

In `backend/indexer.py`, replace the current `chunk_text` (lines 119-126) with:

```python
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def split_sections(text):
    """Split markdown into sections at ATX headings.

    Each section is {"heading": str, "text": str}; the heading line stays in
    its own section's text so it gets embedded with the content it titles.
    Content before the first heading (including YAML frontmatter) is a
    preamble section with heading "". Heading-looking lines inside ``` or
    ~~~ code fences do not split — chat transcripts are full of # comments.
    """
    sections = []
    heading = ""
    lines = []
    in_fence = False

    def close():
        if any(l.strip() for l in lines):
            sections.append({"heading": heading, "text": "\n".join(lines)})

    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            lines.append(line)
            continue
        match = None if in_fence else HEADING_RE.match(line)
        if match:
            close()
            heading = match.group(2).strip()
            lines = [line]
        else:
            lines.append(line)
    close()
    return sections


def chunk_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Heading-aware chunking: one coherent topic per chunk.

    Small adjacent sections merge until the word cap; a single oversized
    section falls back to the plain word window (with overlap) so nothing
    exceeds the cap. Returns [{"text": str, "heading": str}].
    """
    chunks = []
    pending_texts = []
    pending_words = 0
    pending_heading = ""

    def flush():
        nonlocal pending_texts, pending_words, pending_heading
        if pending_texts:
            chunks.append({"text": "\n".join(pending_texts), "heading": pending_heading})
        pending_texts, pending_words, pending_heading = [], 0, ""

    for section in split_sections(text):
        words = section["text"].split()
        if len(words) > chunk_size:
            flush()
            for i in range(0, len(words), chunk_size - overlap):
                piece = " ".join(words[i:i + chunk_size])
                if piece:
                    chunks.append({"text": piece, "heading": section["heading"]})
            continue
        if pending_words + len(words) > chunk_size:
            flush()
        if not pending_texts:
            pending_heading = section["heading"]
        pending_texts.append(section["text"])
        pending_words += len(words)
    flush()
    return chunks
```

(`re` is already imported at the top of indexer.py.)

Note: `index_vault` still calls `chunk_text(content)` and will break until Task 2 — that is expected mid-branch; Task 1's gate is only `test_chunker.py` passing. Do NOT run the full suite in this task; Task 2 restores it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `backend/venv/Scripts/python.exe -m pytest backend/tests/test_chunker.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add backend/indexer.py backend/tests/test_chunker.py
git commit -m "Make chunking heading-aware with code-fence detection and merge-up"
```

---

### Task 2: Index integration — heading metadata

**Files:**
- Modify: `backend/indexer.py:263-273` (the chunk loop in `index_vault`)
- Test: `backend/tests/test_eval_e2e.py` (one new test function)

**Interfaces:**
- Consumes: `chunk_text(content) -> list[{"text", "heading"}]` (Task 1).
- Produces: chunk metadata gains `"heading": str` alongside source/title/tags/category/mtime. Chunk IDs unchanged (`{rel_path}_chunk_{i}`).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_eval_e2e.py`:

```python
def test_chunks_carry_section_heading_metadata(indexed_collection):
    collection, _ = indexed_collection
    got = collection.get(include=["metadatas"])
    headings = {m["source"]: m.get("heading") for m in got["metadatas"]}
    assert headings["Sourdough Starter.md"] == "Sourdough Starter"
    assert headings["Rust Borrow Checker.md"] == "Rust Borrow Checker"
```

(The fixture notes each start with an H1 matching their filename.)

- [ ] **Step 2: Run to verify current state fails**

Run: `backend/venv/Scripts/python.exe -m pytest backend/tests/test_eval_e2e.py -v`
Expected: FAIL — either the new test (missing `heading` key) or all three (TypeError from `index_vault` still treating chunks as strings). Both are the RED state.

- [ ] **Step 3: Update the index_vault chunk loop**

In `backend/indexer.py`, the loop currently reads:

```python
        chunks = chunk_text(content)
        for i, chunk in enumerate(chunks):
            pending_docs.append(chunk)
            pending_metas.append({
                "source": rel_path,
                "title": title,
                "tags": tags_str,
                "category": category,
                "mtime": mtime,
            })
            pending_ids.append(f"{rel_path}_chunk_{i}")
```

Replace with:

```python
        chunks = chunk_text(content)
        for i, chunk in enumerate(chunks):
            pending_docs.append(chunk["text"])
            pending_metas.append({
                "source": rel_path,
                "title": title,
                "tags": tags_str,
                "category": category,
                "mtime": mtime,
                "heading": chunk["heading"],
            })
            pending_ids.append(f"{rel_path}_chunk_{i}")
```

- [ ] **Step 4: Run the full suite**

Run: `backend/venv/Scripts/python.exe -m pytest backend/tests -q`
Expected: 32 passed (21 prior + 10 chunker + 1 heading-metadata). No other callers of `chunk_text` exist (`grep -rn "chunk_text" backend/ --include="*.py"` shows only indexer.py and the new tests — verify and note in your report).

- [ ] **Step 5: Commit**

```bash
git add backend/indexer.py backend/tests/test_eval_e2e.py
git commit -m "Store each chunk's section heading in the index metadata"
```

---

### Task 3: Fold /api/search onto the shared retrieval path

**Files:**
- Modify: `backend/main.py:744-782` (`search_notes`)
- Test: `backend/tests/test_search_endpoint.py` (new)

**Interfaces:**
- Consumes: `retrieval.retrieve(query_text, *, model, collection, scope, k)` (existing).
- Produces: `/api/search` response shape unchanged — `{"results": [{"title", "id", "snippet"}]}`, title-deduped in rank order, snippet = first 150 chars of the chunk, k=6, scope filter semantics identical.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_search_endpoint.py`:

```python
from fastapi.testclient import TestClient

import main
from tests.test_retrieval import FakeModel, FakeCollection

CANNED = {
    "documents": [["alpha chunk one", "alpha chunk two", "beta chunk"]],
    "metadatas": [[
        {"source": "a.md", "title": "Alpha"},
        {"source": "a.md", "title": "Alpha"},
        {"source": "b.md", "title": "Beta"},
    ]],
    "distances": [[0.1, 0.2, 0.3]],
}


def test_search_dedupes_titles_and_keeps_shape(monkeypatch):
    coll = FakeCollection(CANNED)
    monkeypatch.setattr(main, "model", FakeModel())
    monkeypatch.setattr(main, "chroma_collection", coll)
    client = TestClient(main.app)

    resp = client.get("/api/search", params={"q": "alpha", "scope": "chats"})
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results == [
        {"title": "Alpha", "id": "a.md", "snippet": "alpha chunk one"},
        {"title": "Beta", "id": "b.md", "snippet": "beta chunk"},
    ]
    assert coll.last_kwargs["n_results"] == 6
    assert coll.last_kwargs["where"] == {"category": "chat"}


def test_search_empty_query_returns_empty(monkeypatch):
    monkeypatch.setattr(main, "model", FakeModel())
    monkeypatch.setattr(main, "chroma_collection", FakeCollection(CANNED))
    client = TestClient(main.app)
    assert client.get("/api/search", params={"q": "  "}).json() == {"results": []}
```

(`TestClient` used without a `with` block deliberately: lifespan doesn't run, so the monkeypatched globals survive.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `backend/venv/Scripts/python.exe -m pytest backend/tests/test_search_endpoint.py -v`
Expected: first test FAILS on `coll.last_kwargs["n_results"]` (the old inline code queries the real kwargs but through its own path — if it happens to pass, the dedupe/shape assertions still pin behavior; the RED that matters is that `retrieval.retrieve` is not yet in the call path — verify by checking `main.py` still has the inline `chroma_collection.query` call). If both tests pass against the old code, that's acceptable: they are characterization tests; proceed to Step 3 and confirm they still pass after the refactor.

- [ ] **Step 3: Refactor search_notes**

Replace the body of `search_notes` in `backend/main.py` with:

```python
@app.get("/api/search")
def search_notes(q: str = "", scope: str = "notes"):
    global model, chroma_collection
    if not q.strip() or model is None or chroma_collection is None:
        return {"results": []}

    try:
        candidates = retrieval.retrieve(
            q.strip(), model=model, collection=chroma_collection, scope=scope, k=6,
        )
        seen_titles = set()
        items = []
        for c in candidates:
            if c["title"] in seen_titles:
                continue
            seen_titles.add(c["title"])
            items.append({
                "title": c["title"],
                "id": c["source"],
                "snippet": c["chunk"][:150],
            })
        return {"results": items}
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return {"results": []}
```

Behavior parity note for the report: the only delta is the missing-title default ("Untitled" → "Untitled Note"), unreachable because the indexer always writes `title` — same argument accepted in PR 1's review.

- [ ] **Step 4: Run the full suite**

Run: `backend/venv/Scripts/python.exe -m pytest backend/tests -q`
Expected: 34 passed. Also: `backend/venv/Scripts/python.exe -m py_compile backend/main.py` → exit 0.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/tests/test_search_endpoint.py
git commit -m "Fold /api/search onto the shared retrieval path"
```

---

### Task 4: Reindex, measure, record (controller-run)

**Files:**
- Modify: `README.md` (Retrieval quality table + one-line method note)
- Modify: `docs/superpowers/specs/2026-08-05-rag-eval-improvements-design.md` (mark the /api/search gap resolved)

**Interfaces:**
- Consumes: the merged chunker + eval CLI.
- Produces: before/after numbers for the PR description; merge/no-merge decision input.

- [ ] **Step 1: Full reindex with the new chunker**

Run (from `backend/`): `venv/Scripts/python.exe scripts/rebuild_rag_index.py --full`
Expected: completes with a chunks-written count; no errors.

- [ ] **Step 2: Re-run the eval**

Run (from `backend/`): `venv/Scripts/python.exe -m eval.run_eval`
Record hit-rate@4 and MRR@4. Decision gate: improvement → proceed; regression → STOP, report numbers to the user, do not merge; flat → proceed only with the numbers stated plainly and the heading-metadata/citation win described as qualitative.

- [ ] **Step 3: Update README and spec**

README table gains a row under Baseline:

```markdown
| + Heading-aware chunking (split at markdown headings, code-fence aware) | X% | 0.XX |
```

Spec: in the "Known gap" paragraph, append "Resolved in PR 2: `/api/search` now calls `retrieve()`."

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-08-05-rag-eval-improvements-design.md
git commit -m "Record heading-aware chunking retrieval numbers"
```

---

### Task 5: Push and open PR

- [ ] **Step 1: Full validation** — `backend/venv/Scripts/python.exe -m pytest backend/tests -q` (34 passed), py_compile the 6 backend files, `cd frontend && npm run build`.
- [ ] **Step 2: Push + PR** — `git push -u origin rag-heading-chunking`; `gh pr create` with: why (chunks were sliced mid-sentence), what (heading-aware chunker + heading metadata + /api/search unification), before/after table (70.0%/0.496 → new numbers), reindex note (`rebuild_rag_index.py --full` required after merge).
- [ ] **Step 3: Watch CI to green, hand to Bryan for merge.**
