# Second Brain Knowledge Engine

A private, local-first workspace for exploring an Obsidian vault. It combines a fast Rust parser, a FastAPI/ChromaDB retrieval layer, local Qwen through Ollama, and a responsive Next.js interface with an interactive 3D knowledge graph.

## What it includes

- **Workspace overview** with vault totals, recent notes, daily rediscovery, structural health, and separate refresh/index controls.
- **3D knowledge graph** with deterministic layout, explicit and semantic links, tag filters, search, camera focus, keyboard navigation, and context selection.
- **Note reader and editor** with Markdown rendering, save states, Qwen co-writing, Obsidian deep links, and an indexed read-only fallback for OneDrive placeholders.
- **Ask Qwen** with multi-note context chips, local retrieval, source links, clear loading/error states, and no hosted AI dependency.
- **Command search** with `⌘K`, semantic results, direct note opening, and a quick path from a search phrase into Qwen.
- **Vault tools** for creating notes, saving web clips, refreshing graph/health data, and rebuilding the AI search index.

## Architecture

1. **`core` — Rust**  
   Concurrently parses Markdown, wikilinks, tags, and vault structure.
2. **`backend` — FastAPI / Python**  
   Serves graph and note APIs, stores embeddings in ChromaDB, and queries local Qwen through Ollama.
3. **`frontend` — Next.js / React Three Fiber**  
   Provides the desktop workspace, responsive layouts, Markdown tools, chat, and WebGL graph.
4. **`clipper` — Chrome extension**  
   Saves selected web content into the vault inbox.

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

### One-click macOS setup

To keep the frontend and backend running in the background at login, install the
included launch services once:

```bash
./scripts/second-brain install
```

This also installs `Second Brain.app` in `~/Applications`. Open that app or use
the **Second Brain: Start & Open** Run configuration in VS Code to start the
services and open Chrome without managing terminals. The site can then stay
pinned at [http://localhost:3000](http://localhost:3000): right-click its Chrome
tab once and choose **Pin**. The background services continue running when VS
Code and Terminal are closed.

Useful commands:

```bash
./scripts/second-brain status
./scripts/second-brain restart --open
./scripts/second-brain stop
./scripts/second-brain logs
./scripts/second-brain uninstall
```

## Daily workflow

1. Use **Refresh vault** to re-parse notes and update graph/health data.
2. Use **Re-index notes** after substantial note changes so semantic search and Qwen use current embeddings.
3. Open **Knowledge graph** to inspect connections; click a node to read it or Shift-click nodes to add them as Qwen context.
4. Open **Ask Qwen** to search and synthesize across the vault locally.
5. Use the top command search or `⌘K` from anywhere in the workspace.

## Validation

```bash
cd frontend
npm run lint
npx tsc --noEmit
npm run build

cd ../
python3 -m py_compile \
  backend/main.py \
  backend/rag_query.py \
  backend/indexing.py \
  backend/scripts/rebuild_rag_index.py \
  backend/scripts/seed_real_structure.py \
  scripts/chat_archiver.py
PYTHONPATH=backend python3 -m unittest discover -s backend/tests -p 'test_*.py' -v
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
cargo check --manifest-path core/Cargo.toml
cargo test --manifest-path core/Cargo.toml
```

Local runtime data such as `.env`, ChromaDB files, health caches, virtual environments, and Next.js build output is excluded from Git.
