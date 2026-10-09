"""MCP server exposing the vault's hybrid retrieval and grounded answers as tools.

Runs over stdio as a subprocess of an MCP client (Claude Desktop, Claude Code,
Codex, Cursor, VS Code). It is a thin HTTP client for the backend's existing
GET /api/search (search_vault) and POST /api/query (query_vault): it loads no
models and opens no second ChromaDB handle, so the 195 MB index and the two
torch models stay in exactly one process. Running them twice would double ~1.2 GB of resident memory to serve the same index.

Start the backend first, then point a client at this file:

    {
      "mcpServers": {
        "second-brain": {
          "command": "<repo>/backend/venv/Scripts/python.exe",
          "args": ["<repo>/backend/mcp_server.py"]
        }
      }
    }

Install with:  pip install -r requirements-mcp.txt

PRIVACY: this is the one path in the repo where note text leaves the machine.
The server is local, but the caller is a hosted model, so every snippet it
returns (and every query_vault answer, which quotes the notes) is uploaded to
that provider. README.md's "nothing leaves the machine"
describes the web UI and the Ollama generation path. It does not describe this.
"""
import os
import sys
from typing import Literal

import httpx
from mcp.server.fastmcp import FastMCP

BACKEND_URL = os.environ.get("SECOND_BRAIN_API_URL", "http://127.0.0.1:8000")
TIMEOUT_SECONDS = float(os.environ.get("SECOND_BRAIN_MCP_TIMEOUT", "30"))
# /api/query waits on local Ollama generation, which the backend itself allows
# up to 300 s (OLLAMA_CHAT_TIMEOUT_SECONDS in main.py). The 30 s search budget
# would abandon most answers on a CPU-only machine.
QUERY_TIMEOUT_SECONDS = float(os.environ.get("SECOND_BRAIN_MCP_QUERY_TIMEOUT", "300"))

mcp = FastMCP("second-brain")


def _readiness_error() -> str | None:
    """Return an explanation if the backend cannot serve full-quality results.

    Worth the extra round trip: /api/search answers {"results": []} both when
    nothing matched and when the models are still loading, and retrieve_hybrid
    quietly drops the keyword leg and the reranker while they warm up. Without
    this check the tool reports "no matches" for a backend that simply is not
    ready yet, and the calling model has no way to tell the difference.
    """
    try:
        resp = httpx.get(f"{BACKEND_URL}/api/ready", timeout=TIMEOUT_SECONDS)
    except httpx.RequestError:
        return (
            f"The Second Brain backend is not reachable at {BACKEND_URL}. "
            "Start it with `uvicorn main:app` from the backend/ directory, "
            "or set SECOND_BRAIN_API_URL."
        )
    if resp.status_code == 404:
        # An older backend without /api/ready. Degrade rather than refuse.
        return None
    if resp.status_code != 200:
        return f"The backend returned HTTP {resp.status_code} from /api/ready."

    body = resp.json()
    if body.get("ready"):
        return None
    cold = [name for name, loaded in body.get("components", {}).items() if not loaded]
    return (
        "The backend is still loading: "
        + ", ".join(cold)
        + ". Results would be served at reduced quality, so this search was "
        "not run. Wait for startup to finish and try again."
    )


@mcp.tool()
def search_vault(
    query: str,
    scope: Literal["notes", "chats", "all"] = "notes",
) -> str:
    """Search Bryan's Obsidian vault and return the most relevant passages.

    Use this for any question about his own notes, projects, decisions or past
    AI sessions -- anything the answer to which lives in his vault rather than
    in general knowledge. Retrieval is hybrid: semantic embeddings plus keyword
    BM25, fused and then reranked by a cross-encoder.

    Args:
        query: A natural-language question or phrase. Full questions retrieve
            better than bare keywords, because the reranker scores the query
            against passage text.
        scope: "notes" searches written notes only and is the right default.
            "chats" searches exported AI chat transcripts, which make up most
            of the corpus. "all" searches both.

    Returns:
        The backend's configured TOP_K passages, each with note title, path and snippet.
    """
    if not query.strip():
        return "No query given."

    problem = _readiness_error()
    if problem:
        return problem

    try:
        resp = httpx.get(
            f"{BACKEND_URL}/api/search",
            params={"q": query.strip(), "scope": scope},
            timeout=TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
    except httpx.RequestError as exc:
        return f"Could not reach the Second Brain backend at {BACKEND_URL}: {exc}"
    except httpx.HTTPStatusError as exc:
        return f"The backend returned HTTP {exc.response.status_code}."

    results = resp.json().get("results", [])
    if not results:
        return f"No passages matched {query!r} in scope {scope!r}."

    lines = []
    for i, item in enumerate(results, 1):
        lines.append(f"{i}. {item['title']}")
        lines.append(f"   path: {item['id']}")
        lines.append(f"   {item['snippet']}")
    return "\n".join(lines)


def _error_detail(resp: httpx.Response) -> str:
    """FastAPI's {"detail": ...} when present, else the bare status."""
    try:
        detail = resp.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    if detail:
        return f"HTTP {resp.status_code}: {detail}"
    return f"HTTP {resp.status_code}"


@mcp.tool()
def query_vault(
    question: str,
    scope: Literal["notes", "chats", "all"] = "notes",
    notes: list[str] | None = None,
) -> str:
    """Ask Bryan's Obsidian vault a question and get a grounded answer with sources.

    The backend retrieves passages exactly as search_vault does, then has its
    local model (Ollama) write an answer that cites the source notes. Prefer
    search_vault when you want raw passages to reason over yourself; use this
    when a synthesized answer is what you need. It is slower: generation runs
    on Bryan's machine and can take a minute or more.

    Args:
        question: A natural-language question about his notes, projects,
            decisions or past AI sessions.
        scope: "notes" (default) searches written notes only, "chats" searches
            exported AI chat transcripts, "all" searches both. Ignored when
            notes is given.
        notes: Optional vault-relative note paths (the "path" values that
            search_vault returns). When given, retrieval is skipped and the
            answer is grounded in these notes only.

    Returns:
        The answer, then the source notes it was grounded in.
    """
    if not question.strip():
        return "No question given."

    problem = _readiness_error()
    if problem:
        return problem

    payload: dict = {"query": question.strip(), "scope": scope}
    if notes:
        payload["context_nodes"] = notes

    try:
        resp = httpx.post(
            f"{BACKEND_URL}/api/query", json=payload, timeout=QUERY_TIMEOUT_SECONDS
        )
    except httpx.TimeoutException:
        return (
            f"The backend did not answer within {QUERY_TIMEOUT_SECONDS:g} s. "
            "Generation may still be running; raise SECOND_BRAIN_MCP_QUERY_TIMEOUT "
            "or use search_vault for passages without an answer."
        )
    except httpx.RequestError as exc:
        return f"Could not reach the Second Brain backend at {BACKEND_URL}: {exc}"
    if resp.status_code != 200:
        # 500 is what the backend returns when Ollama is down or the model is
        # missing; its detail says which, so pass it through.
        return f"The backend could not answer: {_error_detail(resp)}."

    body = resp.json()
    lines = [(body.get("answer") or "").strip() or "(The backend returned an empty answer.)"]
    sources = body.get("sources") or []
    if sources:
        lines.append("")
        lines.append("Sources:")
        for i, src in enumerate(sources, 1):
            lines.append(f"{i}. {src.get('title', 'Untitled Note')} ({src.get('source', '')})")
    return "\n".join(lines)


if __name__ == "__main__":
    try:
        mcp.run()
    except KeyboardInterrupt:
        sys.exit(0)
