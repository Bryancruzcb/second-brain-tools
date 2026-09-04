"""MCP server exposing the vault's hybrid retrieval as a tool.

Runs over stdio as a subprocess of an MCP client (Claude Desktop, Claude Code,
Cursor, VS Code). It is a thin HTTP client for the backend's existing
GET /api/search: it loads no models and opens no second ChromaDB handle, so
the 195 MB index and the two torch models stay in exactly one process. Running
them twice would double ~1.2 GB of resident memory to serve the same index.

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
returns is uploaded to that provider. README.md's "nothing leaves the machine"
describes the web UI and the Ollama generation path. It does not describe this.
"""
import os
import sys
from typing import Literal

import httpx
from mcp.server.fastmcp import FastMCP

BACKEND_URL = os.environ.get("SECOND_BRAIN_API_URL", "http://127.0.0.1:8000")
TIMEOUT_SECONDS = float(os.environ.get("SECOND_BRAIN_MCP_TIMEOUT", "30"))

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
        Up to six passages, each with its note title, vault path and a snippet.
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


if __name__ == "__main__":
    try:
        mcp.run()
    except KeyboardInterrupt:
        sys.exit(0)
