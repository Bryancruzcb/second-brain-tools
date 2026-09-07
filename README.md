# Second Brain Knowledge Engine

Night Atlas UI for exploring a local Obsidian vault — Notes, Map, Repair, and Ask — with everything running on your own machine.

[![CI Pipeline](https://github.com/Bryancruzcb/second-brain-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/Bryancruzcb/second-brain-tools/actions/workflows/ci.yml)

Nothing leaves the machine. There are no cloud calls and no hosted AI: retrieval is local ChromaDB plus an in-memory BM25 index, generation is Qwen through Ollama, and both LLM clients are constructed against localhost. Map, Notes, and Repair all keep working when Ollama is off — only Ask needs it.

## The hard part: parsing a cloud-synced vault

The vault lives in OneDrive, so half the problem is the filesystem lying to you.

Parallelising the file reads is the obvious first move and it's wrong — it saturates OneDrive's File Provider daemon and the scan dies with `os error 60`. So the Rust core reads files **sequentially on purpose** and parallelises only the CPU-bound work, fanning wikilink and tag extraction across cores with Rayon ([`core/src/main.rs:173`](core/src/main.rs#L173) and [`:194`](core/src/main.rs#L194)).

The second trap is files that aren't really there. OneDrive leaves placeholders — metadata on disk, content not downloaded — and touching one triggers a blocking download or an error. `is_dataless_file()` detects them without reading: `FILE_ATTRIBUTE_OFFLINE` / `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS` on Windows, `SF_DATALESS` on macOS. Those notes are served read-only from the last index instead of failing the request.

Both of these came from running it against my own vault and watching it stall.

![Demo of the vault UI](docs/demo.gif)

*Above: the demo gif may show the previous shell. The current UI is Night Atlas (Notes / Map / Repair / Ask) — open a recent note, inspect the neighborhood map, triage Repair issues, and ask Qwen for a grounded answer with sources.*

## What it includes

- **Notes / Recent** — live recent reel from `GET /api/recent`; open a note via `GET /api/note/{ref}`; inline expand for the selected card.
- **Map** — vault neighborhood graph from `GET /api/graph`; client-side layout of ~42 highest-degree nodes; clicking a node opens the note and can set Ask context.
- **Repair** (Health) — broken links, orphans, and tagless notes from `GET /api/health`; refresh with `POST /api/health/scan`; open a row to jump to the note with a repair callout. When the `vault-core` binary is missing (common on Windows), `backend/health_hygiene.py` derives the same lists from Chroma so the panel is not empty.
- **Ask** — one-shot compose (not a chat transcript) via `POST /api/query`; optional context chip from Map/Notes; clear errors when Ollama is down.
- **Nav** — Notes / Map / Repair / Ask with glow on hover or a brief post-click pulse.
- **API client** — `frontend/src/lib/api.ts`; `NEXT_PUBLIC_API_URL` defaults to `http://127.0.0.1:8000`. See [`ATLAS_MOCK.md`](ATLAS_MOCK.md) for the endpoint table.
- **MCP server** (`backend/mcp_server.py`) on the official Python SDK over stdio, so Claude Desktop, Claude Code, Cursor, or VS Code can call the vault's hybrid search as a tool. It is a thin client over `GET /api/search`, so the index and both torch models stay in one process, and it checks `GET /api/ready` first: that endpoint reports whether the embedding model, Chroma collection, lexical index, and reranker have actually loaded, where `/api/health` answers 200 before they have. This is the one path where note text leaves the machine, because the caller is a hosted model.
- **Clipper / vault archive scripts** — Chrome extension for web clips into the vault inbox, plus `scripts/auto_archive.py` for chat export, health report, incremental re-embed, and backup.

## Retrieval quality

Retrieval is scored against a private set of 40 real questions about my own
vault, 32 about notes and 8 about chat transcripts: each case asks whether
the note that actually answers the question is among the chunks handed to
Qwen. The harness is public (`backend/eval/`); the dataset stays local
because it's my personal notes.

The August sequence, hit-rate@4 and MRR@4 on the index of that day:

| Change | hit-rate@4 | MRR@4 |
|---|---|---|
| Baseline: MiniLM embeddings, 500-word chunks, vector-only | 70.0% | 0.496 |
| + Heading-aware chunking (split at markdown headings, code-fence aware) | 70.0% | 0.529 |
| + Hybrid retrieval (BM25 keyword leg + reciprocal rank fusion) | 70.0% | 0.592 |
| + Cross-encoder reranker (ms-marco-MiniLM over the fused top-20) | 80.0% | 0.694 |
| + bge-small-en-v1.5 embeddings, with the BGE query instruction | 80.0% | 0.713 |

Each change was aimed at a measured diagnosis, not added on faith. The
first three rows improved ranking while hit-rate sat still: the misses
were sibling-note confusion (right folder, wrong note), which is exactly
what a cross-encoder fixes, and it converted four of those twelve misses.
The embedding swap then targeted the misses that never reached the fused
top-20 at all, pulled one of those five into the pool, and the harness
caught something subtler: bge *without* its query instruction was a
hit-rate regression (77.5%), *with* it a modest win, so the instruction
shipped as the default.

### Re-measured 2026-09-04

By September the same pipeline scored 77.5% / 0.715 on the same
questions. The corpus had grown underneath it (4,321 chunks, 4,215 of them
chat transcripts) and nothing was watching. Two changes, both measured on
one frozen copy of that index:

| Configuration | hit-rate@4 | hit-rate@6 | MRR@4 |
|---|---|---|---|
| Shipped in August: depth 20, 4 chunks | 77.5% | | 0.715 |
| Depth 30 | 80.0% | 80.0% | 0.717 |
| Depth 30, one chunk per note, 6 chunks served (shipped now) | 80.0% | 82.5% | 0.717 |

Fetching 30 candidates per leg instead of 20 lifts pool recall from 87.5%
to 90.0% and converts one miss; going deeper than 30 costs reranker time
and converts nothing (still 80.0% at depth 80). Showing more chunks did not
help by itself: at depth 30 the served hit-rate was 80.0% at 4, 6 and 8
chunks with the same eight misses, because the extra slots went to further
chunks of the same long, generic notes (one interview-prep note appears in
32 of the 40 candidate pools). Capping each note to one chunk turns the
extra slots into extra notes: 82.5% at 6 chunks and 85.0% at 8.
Six ships because six chunks plus a full conversation history still fit
the 8,192-token context; eight needs `OLLAMA_NUM_CTX=16384`.

Reranking 30 candidates with `cross-encoder/ms-marco-MiniLM-L-6-v2` takes
about 1.5 s median on this laptop's CPU (Core Ultra 7 155H); an earlier
version of this section claimed ~210 ms, which no longer reproduces.

One honesty note on precision: rebuilding the index and re-running the
eval moves the numbers by about one case (±2.5 points hit-rate, ±0.03
MRR) because Chroma's approximate-nearest-neighbor index is
non-deterministic at build time; within a single build the eval is
exactly reproducible. Treat the tables as a trend, not tenths.

Every retrieval knob is an env var: `EMBEDDING_MODEL`,
`EMBEDDING_QUERY_PREFIX`, `RERANKER_MODEL` (set to `off` on slow CPUs),
`HYBRID_DEPTH`, `RERANK_DEPTH`, `TOP_K`, `MAX_CHUNKS_PER_NOTE` (0 disables
the cap), `OLLAMA_MODEL`. Changing the embedding model requires a full
re-embed: `python scripts/rebuild_rag_index.py --full` from `backend/`.

*The August rows were measured 2026-08-05/06; the September table on
2026-09-04. Two cases accept either of two related notes; the rest label
a single expected note.*

Score it against your own vault:

```bash
cd backend
cp eval/dataset.example.jsonl eval/dataset.jsonl   # then write real cases
python -m eval.run_eval
```

The published number is kept honest by a committed scorecard,
`backend/eval/scorecard.json`: the metrics, the retrieval settings they were
measured under, and a census of the index, with no questions and no note
paths. A test compares it with the shipped settings and with the block below,
so changing a retrieval setting without re-running the eval fails CI. The
nightly archive job re-scores the private set after each incremental index
update and prints a drift warning when the hit-rate falls by two cases or more.

<!-- eval-scorecard:start -->
Recorded 2026-09-04 over 40 cases against an index of 4,321 chunks from 304 files (63 notes, 241 chat transcripts): `BAAI/bge-small-en-v1.5` embeddings with its query instruction, each leg fetched to depth 30, the fused top 30 reranked by `cross-encoder/ms-marco-MiniLM-L-6-v2`, 6 chunks served, at most 1 per note.

| Chunks shown | Hit-rate | MRR |
|---|---|---|
| 4 | 80.0% | 0.717 |
| 6 (shipped) | 82.5% | 0.722 |
<!-- eval-scorecard:end -->

## Architecture

1. **`core` — Rust**  
   Walks the vault and parses Markdown, wikilinks, tags, and structure. Reads sequentially to survive OneDrive; parses in parallel with Rayon.
2. **`backend` — FastAPI / Python**  
   Serves graph and note APIs, stores embeddings in ChromaDB, and queries local Qwen through Ollama. Ships a `Dockerfile` that CI builds on every push, import-tests `main.py` inside the image, and asserts the torch wheel is CPU-only. When `vault-core` is missing, `health_hygiene.py` fills Repair lists from Chroma.
3. **`frontend` — Next.js / React / Tailwind**  
   Night Atlas shell (Notes / Map / Repair / Ask) wired to FastAPI — not React Three Fiber / WebGL.
4. **`clipper` — Chrome extension**  
   Saves selected web content into the vault inbox.
5. **`scripts` — archive pipeline**  
   Exports AI chat transcripts (Claude Code, Codex, Gemini) into the vault as Markdown, regenerates the per-source chat indexes, runs a vault health report, updates the vector index incrementally, and backs up the vault. Designed to run unattended on a schedule.

## Prerequisites

- Node.js 18+ (or [Bun](https://bun.sh) 1.4+; `frontend/package.json` pins `packageManager` to `bun@1.4.2`)
- Python 3.10+
- Rust and Cargo
- [Ollama](https://ollama.com/download) for Ask / Qwen

## Setup

### 1. Configure the vault

Copy `.env.template` to `.env` and set your vault path when it differs from the built-in macOS locations:

```bash
OBSIDIAN_VAULT_PATH="/absolute/path/to/Obsidian Vault"
```

### 2. Start Ollama

```bash
ollama pull qwen2.5
ollama serve
```

Map, Notes, and Repair remain usable when Ollama is offline; only Ask requires it.

### 3. Start the backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### 4. Start the frontend

Prefer Bun (matches `packageManager` in `frontend/package.json`):

```bash
cd frontend
bun install
bun run dev
```

npm still works if you prefer it:

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The backend must be running for live vault data (`NEXT_PUBLIC_API_URL` defaults to `http://127.0.0.1:8000`).

## Daily workflow

1. Start the backend (`uvicorn` on `:8000`) and the frontend (`bun run dev` / `npm run dev` on `:3000`).
2. Browse **Notes** for the live recent reel; expand a card to read it inline.
3. Open **Map** to inspect neighborhood connections; click a node to read it and optionally feed Ask context.
4. Use **Repair** for vault hygiene (broken links, orphans, tagless); refresh the scan when the lists look stale.
5. Use **Ask** for grounded Q&A over the vault (needs Ollama).
6. After `auto_archive` updates the vector index from outside a running backend, restart the backend or re-index so the in-memory BM25 leg matches Chroma.

## Automated chat archiving

`scripts/auto_archive.py` runs the whole maintenance pass in one shot:

1. Export new Claude Code, Codex, and Gemini transcripts into `05 AI Chats/<Source>/<Category>/` (each session becomes one Markdown note, matched by id). A session whose transcript has grown since its last export is re-exported in place — renames are preserved and hand-written summary notes are never overwritten.
2. Delete empty or header-only chat exports.
3. Regenerate every `<Source> Chat Index.md` from the files on disk.
4. Write `00 Home/Vault Health Report.md` (broken links, orphans, missing tags).
5. Incrementally update the ChromaDB vector index — only changed, new, or deleted notes are re-embedded.
6. Zip the vault into `~/Documents/Obsidian Vault Backup/` and keep the newest 7 backups.

Run it manually with `python scripts/auto_archive.py`, or schedule it daily with Windows Task Scheduler pointing at `wscript.exe scripts/run_hidden.vbs` — that runs `scripts/run_auto_archive.cmd` with no visible console and appends to `scripts/auto_archive.log`.

### Topic stubs for project folders

Exported chats still live under `05 AI Chats/`. Topic routing writes small link stubs elsewhere:

- Configure routes in `scripts/topic_routes.json`.
- Transcripts stay in `05 AI Chats/`.
- Matching stubs land under `02 Projects/<Topic>/AI Chat Links/` (and School / Career paths as configured in that JSON).
- Unmatched chats go to `02 Projects/Chat Inbox/AI Chat Links` (`default_route_id`).
- Keyword match wins first; otherwise `scripts/topic_embed.py` (same BGE model as RAG) assigns at ≥0.50 with a margin, else Inbox.
- Confident assignments append `learned_keywords` to `topic_routes.json` (log: `scripts/topic_keyword_learning.log`).
- Backfill existing exports with `python scripts/backfill_topic_stubs.py`.
- `scripts/.auto_archive_last_success` is local-only / gitignored (once-per-day latch for `--daily`).

One caveat: the backend keeps its BM25 keyword index in memory, so if the backend is running while the nightly pass updates the vector index from outside, restart the backend afterward — until then the keyword leg answers from the pre-update snapshot (including notes the pass may have deleted).

Paths are resolved from `OBSIDIAN_VAULT_PATH` and `CHROMA_DB_PATH` (see `.env.template`); the vector index defaults to `backend/chroma_db`.

## Validation

```bash
cd frontend
npm run lint
npx tsc --noEmit
npm run build

cd ../
python3 -m py_compile backend/main.py backend/config.py backend/indexer.py backend/retrieval.py backend/lexical.py backend/eval/dataset.py backend/eval/scoring.py backend/eval/scorecard.py backend/eval/run_eval.py backend/eval/sweep_rerankers.py scripts/*.py
python3 -m pytest backend/tests -q
cargo check --manifest-path core/Cargo.toml
```

Local runtime data such as `.env`, ChromaDB files, health caches, virtual environments, and Next.js build output is excluded from Git.
