"""topic_llm.py — optional Ollama classify for middling Chat Inbox routes.

When keywords miss and embedding is middling (below assign threshold or weak
margin), optionally ask local Ollama (same OLLAMA_MODEL / OLLAMA_URL as Ask Qwen)
to pick among non-inbox topic ids or chat-inbox.

Gate: TOPIC_LLM_CLASSIFY=1 (default off). Offline / timeout / bad JSON → Inbox.
Timeout defaults to 8s so exporters are not blocked on a slow model.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


def llm_classify_enabled() -> bool:
    """TOPIC_LLM_CLASSIFY defaults off for safety."""
    raw = os.environ.get("TOPIC_LLM_CLASSIFY", "")
    return raw.strip().lower() in ("1", "true", "yes", "on")


LLM_TIMEOUT_SECONDS = float(os.environ.get("TOPIC_LLM_TIMEOUT", "8"))
# Only accept a known route id at or above this confidence.
LLM_MIN_CONFIDENCE = float(os.environ.get("TOPIC_LLM_MIN_CONF", "0.75"))
# Middling floor: ignore near-zero embed scores (noise / empty).
LLM_MIN_EMBED = float(os.environ.get("TOPIC_LLM_MIN_EMBED", "0.35"))

_JSON_BLOCK = re.compile(r"\{[^{}]*\}", re.DOTALL)


def _repo_backend() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))


def _ollama_endpoints() -> tuple[str, str]:
    """Same stack as Ask Qwen: backend config OLLAMA_URL / OLLAMA_MODEL."""
    backend = _repo_backend()
    if backend not in os.sys.path:
        os.sys.path.insert(0, backend)
    try:
        import config  # type: ignore

        return config.get_ollama_url(), config.get_ollama_model()
    except Exception:
        url = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        model = os.environ.get("OLLAMA_MODEL", "qwen2.5")
        return url, model


def is_middling_embed(decision: dict[str, Any]) -> bool:
    """True when keyword path missed and embed sat in the ambiguous band."""
    reason = decision.get("reason")
    best = float(decision.get("best") or 0.0)
    if reason not in ("below_threshold", "weak_margin"):
        return False
    return best >= LLM_MIN_EMBED


def _candidate_lines(cfg: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for r in cfg.get("routes", []):
        rid = r.get("id")
        if not rid:
            continue
        title = r.get("title") or rid
        desc = (r.get("description") or "").strip()
        if len(desc) > 120:
            desc = desc[:117].rstrip() + "..."
        if desc:
            lines.append(f"- {rid}: {title} — {desc}")
        else:
            lines.append(f"- {rid}: {title}")
    return lines


def _parse_response(raw: str, known_ids: set[str]) -> tuple[str | None, float]:
    text = (raw or "").strip()
    if not text:
        return None, 0.0
    blob = text
    m = _JSON_BLOCK.search(text)
    if m:
        blob = m.group(0)
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        for tok in re.split(r"[\s,\"']+", text):
            tid = tok.strip().casefold()
            if tid in known_ids:
                return tid, 0.0  # no confidence → reject later
        return None, 0.0
    if not isinstance(data, dict):
        return None, 0.0
    rid = str(data.get("id") or data.get("route") or data.get("topic") or "").strip()
    conf_raw = data.get("confidence", data.get("score", 0))
    try:
        conf = float(conf_raw)
    except (TypeError, ValueError):
        conf = 0.0
    if conf > 1.0 and conf <= 100.0:
        conf = conf / 100.0
    rid_cf = rid.casefold()
    if rid_cf not in known_ids:
        return None, conf
    return rid_cf, conf


def _call_ollama(messages: list[dict[str, str]], timeout: float) -> str:
    url, model = _ollama_endpoints()
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {
            "num_ctx": 2048,
            "num_predict": 80,
            "temperature": 0.0,
        },
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return ((data.get("message") or {}).get("content")) or ""


def classify(text: str, cfg: dict[str, Any]) -> tuple[dict[str, Any] | None, float]:
    """Ask Ollama to pick a route id. Returns (route, confidence) or (None, 0).

    Fail-open: any error / timeout / unknown id / low confidence → (None, 0).
    """
    if not llm_classify_enabled():
        return None, 0.0
    routes = [r for r in cfg.get("routes", []) if r.get("id")]
    if not routes:
        return None, 0.0
    known = {str(r["id"]).casefold() for r in routes}
    default_id = str(cfg.get("default_route_id") or "chat-inbox").casefold()
    known.add(default_id)

    lines = _candidate_lines(cfg)
    if not any(
        l.startswith(f"- {default_id}:") or l.startswith("- chat-inbox:") for l in lines
    ):
        lines.append(f"- {default_id}: Chat Inbox — default when unclear")

    excerpt = re.sub(r"\s+", " ", (text or "").strip())[:1200]
    system = (
        "You route a personal AI chat transcript excerpt to exactly one topic folder. "
        'Reply with JSON only: {"id": "<route_id>", "confidence": <0.0-1.0>}. '
        "Use chat-inbox when unsure or off-topic. Never invent ids."
    )
    user = (
        "Candidate route ids:\n"
        + "\n".join(lines)
        + "\n\nChat excerpt:\n"
        + excerpt
        + "\n\nJSON:"
    )
    try:
        raw = _call_ollama(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            timeout=LLM_TIMEOUT_SECONDS,
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as e:
        print(f"topic_llm: Ollama unavailable or timed out ({e}); keeping Chat Inbox")
        return None, 0.0
    except Exception as e:  # noqa: BLE001 — fail-open for exporters
        print(f"topic_llm: classify failed ({e}); keeping Chat Inbox")
        return None, 0.0

    rid, conf = _parse_response(raw, known)
    if not rid or conf < LLM_MIN_CONFIDENCE:
        if rid:
            print(
                f"topic_llm: rejected id={rid} conf={conf:.3f} "
                f"(need >={LLM_MIN_CONFIDENCE})"
            )
        else:
            print("topic_llm: no usable id/confidence; keeping Chat Inbox")
        return None, conf

    route = next(
        (r for r in routes if str(r.get("id", "")).casefold() == rid),
        None,
    )
    if route is None and rid in (default_id, "chat-inbox"):
        # Synthesize a minimal inbox route if JSON omitted it somehow.
        route = {
            "id": "chat-inbox",
            "title": "Chat Inbox",
            "folder": "02 Projects/Chat Inbox",
        }
    if route is None:
        return None, conf
    print(f"Topic llm: {route.get('id')} conf={conf:.3f}")
    return route, conf
