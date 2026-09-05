import os
import re
import subprocess
import json
import logging
import time
import random
from contextlib import asynccontextmanager
import asyncio
from typing import List, Dict, Any, Optional
import numpy as np
from sklearn.cluster import KMeans
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import chromadb
from sentence_transformers import SentenceTransformer
import httpx

import config
import indexer
import lexical
import retrieval

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("second-brain-backend")

load_dotenv()



# Global variables to load models/database on startup
model = None
chroma_collection = None
lexical_index = None
cross_encoder = None

# Cache configuration
CACHE_FILE = "health_cache.json"
health_cache = {
    "total_notes": 0,
    "total_links": 0,
    "avg_links_per_note": 0.0,
    "broken_links": [],
    "orphaned_notes": [],
    "tagless_notes": [],
    "nodes": [],
    "edges": []
}
is_scanning = False
last_scan_time = 0.0

def _load_fast_sync():
    """Load ChromaDB and Cache on startup."""
    global chroma_collection, health_cache, last_scan_time

    # 1. Load cache if it exists on disk
    if os.path.exists(CACHE_FILE):
        try:
            logger.info("Loading health cache from disk...")
            with open(CACHE_FILE, "r") as f:
                health_cache = json.load(f)
            last_scan_time = os.path.getmtime(CACHE_FILE)
            logger.info("Health cache loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load health cache from disk: {e}")

    # 2. Initialize ChromaDB client
    db_path = config.get_chroma_path()
    logger.info(f"Connecting to ChromaDB at {db_path}...")
    try:
        chroma_client = chromadb.PersistentClient(path=db_path)
        # get_or_create so a fresh machine (no collection yet) doesn't leave
        # chroma_collection stuck at None forever.
        chroma_collection = chroma_client.get_or_create_collection("second_brain")
        logger.info("ChromaDB collection 'second_brain' loaded successfully.")
        # Provenance check: stored vectors only mean anything against the model
        # that produced them. Loud on mismatch, but keep serving — the operator
        # decides whether degraded search beats no backend at all.
        stamped_model = (chroma_collection.metadata or {}).get("embedding_model")
        configured_model = config.get_embedding_model()
        if stamped_model and stamped_model != configured_model:
            logger.error(
                "Embedding model mismatch: index stamped %r but EMBEDDING_MODEL is %r — "
                "vector search will return garbage until scripts/rebuild_rag_index.py --full is run.",
                stamped_model, configured_model,
            )
        elif not stamped_model:
            logger.warning(
                "Index has no embedding-model stamp; run scripts/rebuild_rag_index.py --full to stamp it."
            )
    except Exception as e:
        logger.error(f"Failed to load ChromaDB collection: {e}")

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

def _build_lexical_index():
    """(Re)build the BM25 index; called from a startup thread and again
    synchronously after each ingestion. On failure the previous index (or
    vector-only, if none was ever built) keeps serving."""
    global lexical_index
    if chroma_collection is None:
        logger.warning("Skipping BM25 build: Chroma collection not initialized.")
        return
    try:
        lexical_index = lexical.LexicalIndex.build(chroma_collection)
        logger.info("BM25 lexical index built over %d chunks.", len(lexical_index))
    except Exception as e:
        logger.error(f"Failed to build BM25 index (hybrid degrades to vector-only): {e}")

def _load_reranker_background():
    """Load the cross-encoder reranker; failure or RERANKER_MODEL=off
    serves the fused order instead."""
    global cross_encoder
    name = config.get_reranker_model()
    if config.reranker_disabled(name):
        logger.info("Reranker disabled via RERANKER_MODEL.")
        return
    onnx_file = config.get_reranker_onnx_file()
    logger.info("Loading cross-encoder reranker (%s%s) in background...",
                name, f", ONNX {onnx_file}" if onnx_file else "")
    try:
        cross_encoder = retrieval.load_reranker(name)
        logger.info("Cross-encoder reranker loaded.")
    except Exception as e:
        logger.error(f"Failed to load reranker (serving fused order): {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_fast_sync()
    asyncio.create_task(asyncio.to_thread(_load_model_background))
    asyncio.create_task(asyncio.to_thread(_build_lexical_index))
    asyncio.create_task(asyncio.to_thread(_load_reranker_background))
    yield

app = FastAPI(title="Second Brain Tools API", version="1.0.0", lifespan=lifespan)

# Enable CORS for Next.js frontend on port 3000
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_vault_path() -> str:
    """Resolve the Obsidian vault consistently across every endpoint."""
    return config.get_vault_path()


def resolve_vault_file(relative_path: str) -> str:
    """Resolve a relative note path without allowing traversal outside the vault."""
    vault_path = get_vault_path()
    full_path = os.path.abspath(os.path.join(vault_path, relative_path))
    if os.path.commonpath([vault_path, full_path]) != vault_path:
        raise HTTPException(status_code=403, detail="Path traversal detected")
    return full_path


def get_indexed_note_text(source: str) -> str:
    """Return locally indexed note text when a cloud file is unavailable."""
    global chroma_collection
    if chroma_collection is None:
        return ""
    try:
        result = chroma_collection.get(
            where={"source": source},
            include=["documents"],
        )
        documents = result.get("documents") or []
        # Preserve chunk order while removing any exact duplicates.
        return "\n\n".join(dict.fromkeys(document for document in documents if document))
    except Exception as error:
        logger.warning("Could not read indexed fallback for %s: %s", source, error)
        return ""


# is_dataless_file now lives in indexer.py (the single shared implementation
# used by both the API endpoints below and the vault indexer).
is_dataless_file = indexer.is_dataless_file


def build_graph_from_chroma() -> Dict[str, Any]:
    """Derive graph nodes and edges from the local ChromaDB index.

    This is the primary graph source — it never touches OneDrive, so it
    always works regardless of cloud-sync timeouts.
    """
    global chroma_collection
    if chroma_collection is None:
        return {"nodes": [], "edges": []}

    try:
        # Fetch all chunks (no query — just get everything)
        results = chroma_collection.get(include=["metadatas", "documents", "embeddings"])
        metadatas = results.get("metadatas") or []
        documents = results.get("documents") or []
        # Newer chromadb returns embeddings as a numpy array, whose truth
        # value is ambiguous — never use `or` / bare `if` on it.
        embeddings = results.get("embeddings")
        if embeddings is None:
            embeddings = []
        elif hasattr(embeddings, "tolist"):
            embeddings = embeddings.tolist()

        # Build unique node map: source_path -> {id, label, tags}
        node_map: Dict[str, Dict] = {}
        # Map title -> source for edge resolution
        title_to_source: Dict[str, str] = {}

        for meta in metadatas:
            source = meta.get("source", "")
            title = meta.get("title", source)
            tags_raw = meta.get("tags", "")
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

            if source and source not in node_map:
                node_map[source] = {"id": source, "label": title, "tags": tags}
                title_to_source[title.lower()] = source

        # Build edges by scanning chunk text for [[wikilinks]]
        wikilink_pattern = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
        edge_set: set = set()

        for meta, doc in zip(metadatas, documents):
            source = meta.get("source", "")
            if not source:
                continue
            for match in wikilink_pattern.finditer(doc):
                target_title = match.group(1).strip().lower()
                target_source = title_to_source.get(target_title)
                if target_source and target_source != source:
                    edge = tuple(sorted([source, target_source]))
                    edge_set.add(edge)

        nodes = list(node_map.values())
        
        if embeddings:
            try:
                n_clusters = min(8, len(nodes))
                if n_clusters > 1:
                    emb_array = np.array(embeddings)
                    kmeans = KMeans(n_clusters=n_clusters, random_state=42)
                    labels = kmeans.fit_predict(emb_array)
                    
                    source_to_cluster = {}
                    for idx, meta in enumerate(metadatas):
                        source = meta.get("source", "")
                        if source:
                            source_to_cluster[source] = int(labels[idx])
                            
                    for node in nodes:
                        node["cluster_id"] = source_to_cluster.get(node["id"], 0)
                logger.info(f"Assigned nodes to {n_clusters} clusters.")
            except Exception as e:
                logger.error(f"KMeans clustering failed: {e}")

        explicit_edges = [{"source": e[0], "target": e[1]} for e in edge_set]
        
        ghost_edges = []
        if embeddings:
            try:
                # Query nearest neighbors for all embeddings to find semantic Ghost Links
                nn_results = chroma_collection.query(
                    query_embeddings=embeddings,
                    n_results=4
                )
                
                ghost_edge_set = set()
                for idx, meta in enumerate(metadatas):
                    source = meta.get("source", "")
                    if not source: continue
                    
                    neighbors_meta = nn_results.get('metadatas', [])[idx]
                    distances = nn_results.get('distances', [])[idx]
                    
                    for neighbor_idx, neighbor_meta in enumerate(neighbors_meta):
                        # Filter out matches that aren't semantically close enough
                        dist = distances[neighbor_idx]
                        if dist > 1.2:  # Threshold for semantic similarity
                            continue
                            
                        target_source = neighbor_meta.get("source", "")
                        if target_source and target_source != source:
                            edge = tuple(sorted([source, target_source]))
                            if edge not in edge_set and edge not in ghost_edge_set:
                                ghost_edge_set.add(edge)
                                
                ghost_edges = [{"source": e[0], "target": e[1], "is_ghost": True} for e in ghost_edge_set]
                logger.info(f"Generated {len(ghost_edges)} semantic Ghost Links.")
            except Exception as e:
                logger.error(f"Failed to compute ghost links: {e}")
                
        edges = explicit_edges + ghost_edges

        logger.info(f"ChromaDB graph: {len(nodes)} nodes, {len(edges)} edges.")
        return {"nodes": nodes, "edges": edges}

    except Exception as e:
        logger.error(f"Failed to build graph from ChromaDB: {e}")
        return {"nodes": [], "edges": []}


import shutil

def run_health_scan_sync():
    global health_cache, is_scanning, last_scan_time
    is_scanning = True
    try:
        # Check system PATH first (e.g. inside Docker), fallback to workspace
        binary_path = shutil.which("vault-core")
        if not binary_path:
            home_dir = os.path.expanduser("~")
            binary_path = os.path.join(home_dir, "IdeaProjects/second-brain-tools/core/target/release/vault-core")

        rust_data = None
        if binary_path and os.path.exists(binary_path):
            logger.info("Running background vault-core health checker...")
            try:
                result = subprocess.run(
                    [binary_path, "--json"],
                    capture_output=True, text=True, timeout=3
                )
                if result.returncode == 0 and result.stdout.strip():
                    rust_data = json.loads(result.stdout)
                    # Only trust Rust output if it actually found notes
                    if rust_data.get("total_notes", 0) == 0:
                        logger.warning("vault-core returned 0 notes — likely OneDrive timeout. Falling back to ChromaDB.")
                        rust_data = None
            except subprocess.TimeoutExpired:
                logger.warning("vault-core timed out. Falling back to ChromaDB.")
            except Exception as e:
                logger.warning(f"vault-core failed: {e}. Falling back to ChromaDB.")
        else:
            logger.warning("vault-core binary not found. Falling back to ChromaDB.")

        # Always build graph from ChromaDB (fast, local, reliable)
        graph = build_graph_from_chroma()

        if rust_data:
            # Merge: use Rust stats but always use the ChromaDB graph
            data = {**rust_data, **graph}
        else:
            # Full ChromaDB fallback for stats too
            chroma_note_count = len(graph["nodes"])
            chroma_edge_count = len(graph["edges"])
            data = {
                "total_notes": chroma_note_count,
                "total_links": chroma_edge_count,
                "avg_links_per_note": round(chroma_edge_count / chroma_note_count, 2) if chroma_note_count else 0.0,
                "broken_links": health_cache.get("broken_links", []),
                "orphaned_notes": [],
                "tagless_notes": [],
                **graph
            }

        health_cache = data
        last_scan_time = time.time()

        with open(CACHE_FILE, "w") as f:
            json.dump(data, f)
        logger.info("Health scan complete and cache updated.")

    except Exception as e:
        logger.error(f"Failed during background health scan: {e}")
    finally:
        is_scanning = False

class QueryRequest(BaseModel):
    query: str
    context_nodes: Optional[List[str]] = None
    scope: Optional[str] = "notes"  # "notes", "chats", "all"
    history: Optional[List[Dict[str, str]]] = None  # prior turns: {role, content}


# History budget: ~12K chars ≈ 3K tokens, which fits the 8K default context
# window alongside 4 retrieved chunks (~2.7K tokens), the system prompt, and
# a 1K-token answer.
MAX_HISTORY_MESSAGES = 6
MAX_HISTORY_MESSAGE_CHARS = 3000
MAX_HISTORY_TOTAL_CHARS = 12000

OLLAMA_CHAT_TIMEOUT_SECONDS = 300


def clean_history(raw) -> List[Dict[str, str]]:
    """Sanitize client-supplied conversation history.

    Keeps only well-formed user/assistant turns, newest-first within the
    char budget, so a hostile or bloated payload can't blow the context
    window or smuggle in system-role messages.
    """
    if not raw:
        return []
    cleaned = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = (item.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        cleaned.append({"role": role, "content": content[:MAX_HISTORY_MESSAGE_CHARS]})

    cleaned = cleaned[-MAX_HISTORY_MESSAGES:]

    kept, total = [], 0
    for msg in reversed(cleaned):
        total += len(msg["content"])
        if total > MAX_HISTORY_TOTAL_CHARS:
            break
        kept.append(msg)
    return list(reversed(kept))


def ollama_chat(messages: List[Dict[str, str]], max_tokens: int) -> str:
    """Call Ollama's native chat API.

    The OpenAI-compatible endpoint cannot set num_ctx, so long prompts were
    silently truncated from the top at Ollama's small default window.
    """
    response = httpx.post(
        f"{config.get_ollama_url()}/api/chat",
        json={
            "model": config.get_ollama_model(),
            "messages": messages,
            "stream": False,
            "options": {
                "num_ctx": config.get_ollama_num_ctx(),
                "num_predict": max_tokens,
            },
        },
        timeout=OLLAMA_CHAT_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return (response.json().get("message") or {}).get("content") or ""


class QueryResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]
    api_configured: bool

@app.get("/api/health")
def get_health():
    global health_cache, is_scanning, last_scan_time
    return {
        "data": health_cache,
        "is_scanning": is_scanning,
        "last_scan_time": last_scan_time
    }

@app.get("/api/ready")
def get_ready():
    """Which retrieval components have finished loading.

    /api/health answers 200 from a cached blob the instant the process starts,
    so it cannot tell a warm backend from one still loading models. That gap
    matters because retrieval degrades *silently*: retrieve_hybrid falls back
    to vector-only with no rerank when lexical_index or cross_encoder is still
    None, which is the configuration that measured 70% hit-rate, not 80%. A
    caller sees plausible results at the wrong quality and no error.

    The frontend polls /api/health and is unaffected. Anything that is not the
    frontend -- the MCP server, a container smoke test, a load balancer --
    should gate on this instead.
    """
    global model, chroma_collection, lexical_index, cross_encoder
    components = {
        "embedding_model": model is not None,
        "chroma_collection": chroma_collection is not None,
        "lexical_index": lexical_index is not None,
        # A disabled reranker is a deliberate configuration, not a cold start.
        "reranker": cross_encoder is not None
        or config.reranker_disabled(config.get_reranker_model()),
    }
    return {"ready": all(components.values()), "components": components}

@app.post("/api/health/scan")
def trigger_scan(background_tasks: BackgroundTasks):
    global is_scanning
    if is_scanning:
        return {"status": "scanning", "message": "A scan is already in progress."}
    
    background_tasks.add_task(run_health_scan_sync)
    return {"status": "started", "message": "Scan started in background."}

def run_ingestion_sync():
    global chroma_collection, model
    if not chroma_collection or not model:
        logger.error("Cannot ingest: db or model not loaded yet.")
        return

    logger.info("Starting vector ingestion (incremental)...")
    summary = indexer.index_vault(chroma_collection, model, incremental=True, log=logger.info)
    if summary.get("aborted"):
        # Nothing was written, so the BM25 snapshot is still current; the only
        # thing left to do is make the refusal impossible to miss in the log.
        logger.error("Vector ingestion aborted: %s", summary["aborted"])
        return
    if summary.get("batches_failed"):
        logger.error(
            "%d embedding batch(es) FAILED during ingestion — the index is incomplete; "
            "those chunks are missing from search until the next successful run.",
            summary["batches_failed"],
        )
    logger.info(
        f"Vector ingestion complete! {summary['files_scanned']} scanned, "
        f"{summary['files_reindexed']} reindexed, {summary['files_skipped']} skipped, "
        f"{summary['files_pruned']} pruned, {summary['chunks_written']} chunks written."
    )
    # The BM25 index is a snapshot of the collection: rebuild it or the
    # keyword leg keeps answering from the pre-ingestion corpus.
    _build_lexical_index()


@app.post("/api/index")
def trigger_index(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_ingestion_sync)
    return {"status": "started", "message": "Vector indexing started in background."}

@app.get("/api/graph")
def get_graph():
    global health_cache
    nodes = health_cache.get("nodes", [])
    edges = health_cache.get("edges", [])
    # If no cached graph yet, build on-demand from ChromaDB
    if not nodes:
        graph = build_graph_from_chroma()
        nodes = graph["nodes"]
        edges = graph["edges"]
    return {"nodes": nodes, "edges": edges}

@app.post("/api/query", response_model=QueryResponse)
def run_query(request: QueryRequest):
    global model, chroma_collection, lexical_index, cross_encoder

    if model is None or chroma_collection is None:
        raise HTTPException(status_code=503, detail="Vector search engine or embedding model is not initialized.")
        
    query_text = request.query.strip()
    if not query_text:
        raise HTTPException(status_code=400, detail="Query text cannot be empty.")
        
    try:
        history = clean_history(request.history)

        # 1. Embed the retrieval text. Follow-ups like "expand on that" carry
        # no topic words themselves, so fold the last couple of user turns
        # into the embedding to keep retrieval anchored to the conversation.
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
            candidates = retrieval.retrieve_hybrid(
                retrieval_text,
                model=model,
                collection=chroma_collection,
                lexical=lexical_index,
                cross_encoder=cross_encoder,
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
                # A lexical-only fused candidate carries "score", not "distance".
                "distance": c.get("distance", 0.0),
            })
            context_chunks.append(f"From Note: {c['title']}\nContent: {c['chunk']}")

        # 4. Generate prompt context
        context_str = "\n\n".join(context_chunks)
        
        # 5. Generate through local Ollama, carrying the conversation so far
        api_configured = True
        logger.info(
            "Calling local %s via Ollama (%d history turns)...",
            config.get_ollama_model(), len(history),
        )

        system_prompt = (
            "You are an expert Second Brain Personal AI Assistant. "
            "Answer the user's question using ONLY the provided Markdown note snippets and the conversation so far as context. "
            "If the context doesn't contain the answer, explain that you couldn't find sufficient information in their notes "
            "but supply whatever relevant details are in the context. "
            "Always cite the source notes by name (e.g., 'According to your notes on [Note Name]...') in a professional, senior portfolio-grade format."
        )

        messages = (
            [{"role": "system", "content": system_prompt}]
            + history
            + [{"role": "user", "content": f"Context snippets:\n{context_str}\n\nQuestion: {query_text}"}]
        )
        answer_text = ollama_chat(messages, max_tokens=1024)
        
        # Emoji/ANSI print here crashed the endpoint on Windows (cp1252
        # stdout raises UnicodeEncodeError inside the handler -> 500).
        logger.info("Model response generated (%d chars, %d sources).", len(answer_text), len(sources))
                
        return QueryResponse(answer=answer_text, sources=sources, api_configured=api_configured)
        
    except Exception as e:
        logger.error(f"RAG search query failure: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class CreateNoteRequest(BaseModel):
    title: str
    content: str = ""

@app.post("/api/note/create")
def create_new_note(request: CreateNoteRequest):
    """Create a root-level Markdown note.

    This static route must stay above the dynamic /api/note/{title} POST route so
    FastAPI does not interpret the word "create" as a note title.
    """
    home_dir = os.path.expanduser("~")
    vault_path = os.environ.get("OBSIDIAN_VAULT_PATH") or os.path.join(home_dir, "OneDrive/Documents/Obsidian Vault")
    if not os.path.exists(vault_path):
        vault_path = os.path.join(home_dir, "Library/CloudStorage/OneDrive-Personal/Documents/Obsidian Vault")

    safe_title = "".join(c for c in request.title if c.isalnum() or c in " -_").strip()
    if not safe_title:
        safe_title = "Untitled Note"

    target_path = os.path.join(vault_path, f"{safe_title}.md")

    if not os.path.abspath(target_path).startswith(os.path.abspath(vault_path)):
        raise HTTPException(status_code=403, detail="Path traversal detected")

    if os.path.exists(target_path):
        raise HTTPException(status_code=409, detail="A note with that title already exists")

    content = request.content or f"# {request.title}\n\n"
    try:
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"status": "success", "title": safe_title}
    except Exception as e:
        logger.error(f"Create note failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/note/{note_ref:path}")
def get_note_content(note_ref: str):
    global health_cache
    nodes = health_cache.get("nodes", [])
    normalized_ref = note_ref.lower()
    node = next(
        (
            n for n in nodes
            if n.get("id", "").lower() == normalized_ref
            or n.get("label", "").lower() == normalized_ref
        ),
        None,
    )

    if not node:
        raise HTTPException(status_code=404, detail="Note not found")

    rel_path = node["id"]
    full_path = resolve_vault_file(rel_path)
        
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Note file not found at expected path")

    if is_dataless_file(full_path):
        indexed_content = get_indexed_note_text(rel_path)
        if indexed_content:
            return {
                "title": node["label"],
                "content": indexed_content,
                "read_only_fallback": True,
            }

    try:
        with open(full_path, "r", encoding="utf-8") as file_obj:
            return {"title": node["label"], "content": file_obj.read()}
    except OSError as error:
        indexed_content = get_indexed_note_text(rel_path)
        if indexed_content:
            return {
                "title": node["label"],
                "content": indexed_content,
                "read_only_fallback": True,
            }
        raise HTTPException(status_code=500, detail=str(error))

class NoteSaveRequest(BaseModel):
    content: str

@app.post("/api/note/{note_ref:path}")
def save_note_content(note_ref: str, request: NoteSaveRequest):
    global health_cache
    nodes = health_cache.get("nodes", [])
    normalized_ref = note_ref.lower()
    node = next(
        (
            n for n in nodes
            if n.get("id", "").lower() == normalized_ref
            or n.get("label", "").lower() == normalized_ref
        ),
        None,
    )

    if node:
        target_path = resolve_vault_file(node["id"])
    else:
        # Create at root if doesn't exist. Sanitize title first.
        safe_title = os.path.splitext(os.path.basename(note_ref))[0]
        target_path = resolve_vault_file(f"{safe_title}.md")
        
    try:
        with open(target_path, "w", encoding="utf-8") as file_obj:
            file_obj.write(request.content)
        return {"status": "success", "message": "Note saved"}
    except Exception as e:
        logger.error(f"Failed to save note: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class CowriteRequest(BaseModel):
    content: str
    
@app.post("/api/cowrite")
def run_cowrite(request: CowriteRequest):
    prompt = (
        "You are an AI co-writer. Continue the following markdown text naturally. "
        "Provide ONLY the continuation text, do NOT repeat the provided text, and do not include conversational filler.\n\n"
        f"{request.content[-2000:]}"
    )
    try:
        completion = ollama_chat([{"role": "user", "content": prompt}], max_tokens=256)
        return {"completion": completion}
    except Exception as e:
        logger.error(f"Co-write failure: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class ClipRequest(BaseModel):
    title: str
    content: str
    url: str

@app.post("/api/clip")
def save_web_clip(request: ClipRequest):
    home_dir = os.path.expanduser("~")
    vault_path = os.environ.get("OBSIDIAN_VAULT_PATH") or os.path.join(home_dir, "OneDrive/Documents/Obsidian Vault")
    if not os.path.exists(vault_path):
        vault_path = os.path.join(home_dir, "Library/CloudStorage/OneDrive-Personal/Documents/Obsidian Vault")
        
    inbox_dir = os.path.join(vault_path, "Inbox")
    if not os.path.exists(inbox_dir):
        os.makedirs(inbox_dir, exist_ok=True)
        
    safe_title = "".join(c for c in request.title if c.isalnum() or c in " -_").strip()
    if not safe_title: safe_title = "Clipped Note"
    
    target_path = os.path.join(inbox_dir, f"{safe_title}.md")
    
    file_content = f"# {request.title}\n\n**Source**: {request.url}\n\n{request.content}\n"
    
    try:
        with open(target_path, "a", encoding="utf-8") as f:
            f.write(file_content + "\\n---\\n")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Clip save failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/digest")
def get_daily_digest():
    global health_cache
    nodes = health_cache.get("nodes", [])
    if not nodes:
        return {"digest": []}
    
    # Stable for the current day so the review set does not jump during polling.
    daily_random = random.Random(time.strftime("%Y-%m-%d"))
    selected = daily_random.sample(nodes, min(3, len(nodes)))
    return {"digest": selected}

@app.get("/api/recent")
def get_recent_notes():
    # The health cache already contains every indexed note. Stat those known files
    # instead of recursively walking a cloud-synced vault on every dashboard load.
    candidates = []
    for node in health_cache.get("nodes", []):
        try:
            path = resolve_vault_file(node["id"])
            if os.path.isfile(path):
                candidates.append((os.path.getmtime(path), node, path))
        except (OSError, HTTPException, KeyError):
            continue

    candidates.sort(key=lambda item: item[0], reverse=True)
    recent = []
    for mtime, node, path in candidates[:6]:
        indexed_content = get_indexed_note_text(node["id"])
        preview = indexed_content[:200].strip()
        recent.append({
            "title": node.get("label") or os.path.splitext(os.path.basename(path))[0],
            "id": node["id"],
            "mtime": mtime,
            "preview": preview,
        })

    return {"notes": recent}

@app.get("/api/search")
def search_notes(q: str = "", scope: str = "notes"):
    global model, chroma_collection, lexical_index, cross_encoder
    if not q.strip() or model is None or chroma_collection is None:
        return {"results": []}

    try:
        candidates = retrieval.retrieve_hybrid(
            q.strip(), model=model, collection=chroma_collection,
            lexical=lexical_index, cross_encoder=cross_encoder, scope=scope, k=6,
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


if __name__ == "__main__":
    import uvicorn
    # Load settings from environment or fallback
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run("main:app", host=host, port=port, reload=True)
