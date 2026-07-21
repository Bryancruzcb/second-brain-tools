# Second Brain Knowledge Engine

Explore your Obsidian notes as a 3D map and ask questions about them, with everything running on your own machine.

[![CI Pipeline](https://github.com/Bryancruzcb/second-brain-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/Bryancruzcb/second-brain-tools/actions/workflows/ci.yml)

Nothing leaves the machine. There are no cloud calls and no hosted AI: retrieval is local ChromaDB, generation is Qwen through Ollama, and both LLM clients are constructed against localhost. The graph, note reader, and health tools all keep working when Ollama is off — only the Qwen features need it.

## The hard part: parsing a cloud-synced vault

The vault lives in OneDrive, so half the problem is the filesystem lying to you.

Parallelising the file reads is the obvious first move and it's wrong — it saturates OneDrive's File Provider daemon and the scan dies with `os error 60`. So the Rust core reads files **sequentially on purpose** and parallelises only the CPU-bound work, fanning wikilink and tag extraction across cores with Rayon ([`core/src/main.rs:173`](core/src/main.rs#L173) and [`:194`](core/src/main.rs#L194)).

The second trap is files that aren't really there. OneDrive leaves placeholders — metadata on disk, content not downloaded — and touching one triggers a blocking download or an error. `is_dataless_file()` detects them without reading: `FILE_ATTRIBUTE_OFFLINE` / `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS` on Windows, `SF_DATALESS` on macOS. Those notes are served read-only from the last index instead of failing the request.

Both of these came from running it against my own vault and watching it stall.

> **DEMO GOES HERE.** Record 8–12 seconds at 1280×720: open the 3D graph, click a node, Shift-click two more to add them as context, ask Qwen a question, land on the answer with its source links visible. Save as `docs/demo.gif` and replace this block with `![Demo](docs/demo.gif)`.

## What it includes

- **Workspace overview** with vault totals, recent notes, daily rediscovery, structural health, and separate refresh/index controls.
- **3D knowledge graph** with deterministic layout, explicit and semantic links, tag filters, search, camera focus, keyboard navigation, and context selection.
- **Note reader and editor** with Markdown rendering, save states, Qwen co-writing, Obsidian deep links, and an indexed read-only fallback for OneDrive placeholders.
- **Ask Qwen** with multi-note context chips, local retrieval, source links, clear loading/error states, and no hosted AI dependency.
- **Command search** with `⌘K`, semantic results, direct note opening, and a quick path from a search phrase into Qwen.
- **Vault tools** for creating notes, saving web clips, refreshing graph/health data, and rebuilding the AI search index.

## Architecture

1. **`core` — Rust**  
   Walks the vault and parses Markdown, wikilinks, tags, and structure. Reads sequentially to survive OneDrive; parses in parallel with Rayon.
2. **`backend` — FastAPI / Python**  
   Serves graph and note APIs, stores embeddings in ChromaDB, and queries local Qwen through Ollama.
3. **`frontend` — Next.js / React Three Fiber**  
   Provides the desktop workspace, responsive layouts, Markdown tools, chat, and WebGL graph.
4. **`clipper` — Chrome extension**  
   Saves selected web content into the vault inbox.
5. **`scripts` — archive pipeline**  
   Exports AI chat transcripts (Claude Code, Codex, Gemini) into the vault as Markdown, regenerates the per-source chat indexes, runs a vault health report, updates the vector index incrementally, and backs up the vault. Designed to run unattended on a schedule.

## Prerequisites

- Node.js 18+
- Python 3.10+
- Rust and Cargo
- [Ollama](https://ollama.com/download) for Qwen chat and co-writing

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

The graph, note reader, and health tools remain usable when Ollama is offline; only Qwen features require it.

### 3. Start the backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### 4. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Daily workflow

1. Use **Refresh vault** to re-parse notes and update graph/health data.
2. Use **Re-index notes** after substantial note changes so semantic search and Qwen use current embeddings.
3. Open **Knowledge graph** to inspect connections; click a node to read it or Shift-click nodes to add them as Qwen context.
4. Open **Ask Qwen** to search and synthesize across the vault locally.
5. Use the top command search or `⌘K` from anywhere in the workspace.

## Automated chat archiving

`scripts/auto_archive.py` runs the whole maintenance pass in one shot:

1. Export new Claude Code, Codex, and Gemini transcripts into `05 AI Chats/<Source>/<Category>/` (each session becomes one Markdown note; already-exported sessions are skipped by id).
2. Delete empty or header-only chat exports.
3. Regenerate every `<Source> Chat Index.md` from the files on disk.
4. Write `00 Home/Vault Health Report.md` (broken links, orphans, missing tags).
5. Incrementally update the ChromaDB vector index — only changed, new, or deleted notes are re-embedded.
6. Zip the vault into `~/Documents/Obsidian Vault Backup/` and keep the newest 7 backups.

Run it manually with `python scripts/auto_archive.py`, or schedule `scripts/run_auto_archive.cmd` (Windows Task Scheduler) to run it daily; it appends to `scripts/auto_archive.log`.

Paths are resolved from `OBSIDIAN_VAULT_PATH` and `CHROMA_DB_PATH` (see `.env.template`); the vector index defaults to `backend/chroma_db`.

## Validation

```bash
cd frontend
npm run lint
npx tsc --noEmit
npm run build

cd ../
python3 -m py_compile backend/main.py backend/config.py backend/indexer.py scripts/*.py
cargo check --manifest-path core/Cargo.toml
```

Local runtime data such as `.env`, ChromaDB files, health caches, virtual environments, and Next.js build output is excluded from Git.
