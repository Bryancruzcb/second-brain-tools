#!/usr/bin/env python3
"""Weekly Repair digest: a read-only summary of Night Atlas vault hygiene.

The Repair view lists broken links, orphaned notes and tagless notes from the
backend's last health scan (``GET /api/health``). This script turns that same
data into a short Markdown report, optionally with a week-over-week diff.

It is read-only by construction:

* it only ever issues ``GET /api/health`` (never ``POST /api/health/scan``,
  ``/api/index`` or any note route), or, offline, it opens
  ``backend/health_cache.json`` for reading;
* it never touches the vault, ChromaDB or the backend's cache file;
* the only files it writes are the ones you name with ``--out`` and
  ``--json-out``, and it refuses to write those inside the vault
  (``OBSIDIAN_VAULT_PATH``) or onto the backend's own cache file.

Because ``GET /api/health`` serves the cached result of the last scan, the
digest reports how old that scan is and flags it when it is older than
``--stale-days``; refreshing it is a deliberate click on Repair -> Scan, not
something a report should do behind your back.

Usage (from the repo root, on the machine running the backend):

    python scripts/repair_digest.py --out repair-digest.md --json-out repair-digest.json \
        --previous last-week.json

Exit codes: 0 digest produced; 2 no data source reachable.
Stdlib only, so the backend venv or any Python 3.8+ works.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_URL = "http://127.0.0.1:8000"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CACHE = os.path.join(REPO_ROOT, "backend", "health_cache.json")

CATEGORIES = ("broken_links", "orphaned_notes", "tagless_notes")
LABELS = {
    "broken_links": "Broken links",
    "orphaned_notes": "Orphaned notes",
    "tagless_notes": "Tagless notes",
}


class DigestError(Exception):
    pass


def fetch_health(base_url: str, timeout: float = 10.0) -> Dict[str, Any]:
    """GET /api/health. The only HTTP request this module makes."""
    url = base_url.rstrip("/") + "/api/health"
    req = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise DigestError(f"backend not reachable at {url}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        raise DigestError(f"unexpected /api/health payload from {url}")
    return {
        "source": url,
        "data": payload["data"],
        "is_scanning": bool(payload.get("is_scanning")),
        "last_scan_time": float(payload.get("last_scan_time") or 0.0),
    }


def read_cache(path: str) -> Dict[str, Any]:
    """Read backend/health_cache.json (opened read-only) when the backend is down."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        mtime = os.path.getmtime(path)
    except (OSError, ValueError) as exc:
        raise DigestError(f"cannot read health cache {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise DigestError(f"unexpected health cache contents in {path}")
    return {"source": path, "data": data, "is_scanning": False, "last_scan_time": mtime}


def item_key(category: str, item: Dict[str, Any]) -> str:
    if category == "broken_links":
        return f"{item.get('source', '')} -> {item.get('target', '')}"
    return str(item.get("path") or item.get("title") or "")


def item_line(category: str, item: Dict[str, Any]) -> str:
    if category == "broken_links":
        title = item.get("source_title") or item.get("source") or "?"
        return f"`{title}` links to missing `{item.get('target', '?')}`"
    title = item.get("title") or item.get("path") or "?"
    path = item.get("path") or ""
    line = f"`{title}`" + (f" ({path})" if path and path != title else "")
    if category == "tagless_notes":
        sugg = [s for s in (item.get("suggestions") or []) if s][:3]
        if sugg:
            line += " - suggested: " + ", ".join(sugg)
    return line


def summarize(snapshot: Dict[str, Any], now: Optional[float] = None, stale_days: float = 7.0) -> Dict[str, Any]:
    """Machine-readable digest; also what --previous expects next week."""
    now = time_now() if now is None else now
    data = snapshot["data"]
    last = snapshot.get("last_scan_time") or 0.0
    age_days = (now - last) / 86400.0 if last else None
    items = {c: [i for i in (data.get(c) or []) if isinstance(i, dict)] for c in CATEGORIES}
    return {
        "generated_at": _iso(now),
        "source": snapshot["source"],
        "last_scan_time": _iso(last) if last else None,
        "scan_age_days": round(age_days, 2) if age_days is not None else None,
        "stale": age_days is None or age_days > stale_days,
        "is_scanning": snapshot.get("is_scanning", False),
        "total_notes": data.get("total_notes", 0),
        "total_links": data.get("total_links", 0),
        "counts": {c: len(items[c]) for c in CATEGORIES},
        "keys": {c: sorted({item_key(c, i) for i in items[c]}) for c in CATEGORIES},
        "_items": items,
    }


def diff(current: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> Optional[Dict[str, Dict[str, List[str]]]]:
    if not previous:
        return None
    out = {}
    for c in CATEGORIES:
        now_keys = set(current["keys"][c])
        then_keys = set((previous.get("keys") or {}).get(c) or [])
        out[c] = {"new": sorted(now_keys - then_keys), "resolved": sorted(then_keys - now_keys)}
    return out


def render_markdown(summary: Dict[str, Any], delta=None, previous=None, limit: int = 25, stale_days: float = 7.0) -> str:
    lines: List[str] = []
    lines.append(f"# Night Atlas Repair digest - {summary['generated_at'][:10]}")
    lines.append("")
    lines.append("Read-only report from the last Repair scan; nothing was changed.")
    lines.append("")
    if summary["last_scan_time"]:
        lines.append(f"- Last scan: {summary['last_scan_time']} ({summary['scan_age_days']} days ago)")
    else:
        lines.append("- Last scan: never (the backend has no scan result yet)")
    lines.append(f"- Source: {summary['source']}")
    lines.append(f"- Vault: {summary['total_notes']} notes, {summary['total_links']} links")
    if summary["stale"]:
        lines.append("")
        lines.append(
            f"> **Stale:** the last scan is older than {stale_days:g} days (or missing). "
            "Open Repair and press Scan to refresh it; this digest does not trigger scans."
        )
    if summary["is_scanning"]:
        lines.append("")
        lines.append("> A scan was running when this digest was taken; numbers may change.")
    lines.append("")
    lines.append("| Issue | Count | Change |")
    lines.append("|---|---|---|")
    for c in CATEGORIES:
        change = ""
        if previous:
            before = (previous.get("counts") or {}).get(c, 0)
            d = summary["counts"][c] - before
            change = f"{d:+d} (was {before})"
        lines.append(f"| {LABELS[c]} | {summary['counts'][c]} | {change} |")
    total = sum(summary["counts"].values())
    lines.append(f"| **To fix** | **{total}** | |")
    if delta:
        lines.append("")
        lines.append("## Since last digest")
        lines.append("")
        for c in CATEGORIES:
            new, gone = delta[c]["new"], delta[c]["resolved"]
            lines.append(f"- {LABELS[c]}: {len(new)} new, {len(gone)} resolved")
            for k in new[:limit]:
                lines.append(f"  - new: `{k}`")
            if len(new) > limit:
                lines.append(f"  - ...and {len(new) - limit} more new")
    for c in CATEGORIES:
        items = summary["_items"][c]
        lines.append("")
        lines.append(f"## {LABELS[c]} ({len(items)})")
        lines.append("")
        if not items:
            lines.append("None.")
            continue
        for item in items[:limit]:
            lines.append(f"- {item_line(c, item)}")
        if len(items) > limit:
            lines.append(f"- ...and {len(items) - limit} more (see the Repair view)")
    lines.append("")
    return "\n".join(lines)


def _realpath(p: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(p)))


def check_output_path(path: str, cache_path: str = DEFAULT_CACHE) -> None:
    """Refuse to write inside the vault or over the backend's cache."""
    target = _realpath(path)
    if target == _realpath(cache_path):
        raise DigestError(f"refusing to overwrite the backend health cache: {path}")
    vault = os.environ.get("OBSIDIAN_VAULT_PATH")
    if vault:
        root = _realpath(vault)
        if target == root or target.startswith(root.rstrip(os.sep) + os.sep):
            raise DigestError(f"refusing to write inside the vault ({vault}): {path}")


def time_now() -> float:
    import time
    return time.time()


def _iso(ts: float) -> str:
    return _dt.datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def load_snapshot(url: str, cache: str, mode: str) -> Tuple[Dict[str, Any], List[str]]:
    notes: List[str] = []
    if mode in ("auto", "api"):
        try:
            return fetch_health(url), notes
        except DigestError as exc:
            if mode == "api":
                raise
            notes.append(f"{exc}; falling back to {cache}")
    return read_cache(cache), notes


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Read-only weekly digest of the Night Atlas Repair view.")
    ap.add_argument("--url", default=os.environ.get("NIGHT_ATLAS_API_URL", DEFAULT_URL),
                    help=f"backend base URL (default {DEFAULT_URL})")
    ap.add_argument("--cache-file", default=DEFAULT_CACHE, help="backend health_cache.json for offline mode")
    ap.add_argument("--source", choices=("auto", "api", "cache"), default="auto",
                    help="auto: API, then cache file if the backend is down (default)")
    ap.add_argument("--out", help="write the Markdown digest here (default: stdout)")
    ap.add_argument("--json-out", help="also write the machine-readable summary (feed it to --previous next week)")
    ap.add_argument("--previous", help="last week's --json-out file, for a week-over-week diff")
    ap.add_argument("--limit", type=int, default=25, help="items listed per category (default 25)")
    ap.add_argument("--stale-days", type=float, default=7.0, help="flag scans older than this (default 7)")
    args = ap.parse_args(argv)

    try:
        for p in (args.out, args.json_out):
            if p:
                check_output_path(p, args.cache_file)
        snapshot, notes = load_snapshot(args.url, args.cache_file, args.source)
    except DigestError as exc:
        print(f"repair_digest: {exc}", file=sys.stderr)
        return 2
    for n in notes:
        print(f"repair_digest: {n}", file=sys.stderr)

    previous = None
    if args.previous:
        try:
            with open(args.previous, "r", encoding="utf-8") as fh:
                previous = json.load(fh)
        except (OSError, ValueError) as exc:
            print(f"repair_digest: ignoring --previous ({exc})", file=sys.stderr)

    summary = summarize(snapshot, stale_days=args.stale_days)
    delta = diff(summary, previous)
    md = render_markdown(summary, delta, previous, limit=args.limit, stale_days=args.stale_days)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
    else:
        sys.stdout.write(md)
    if args.json_out:
        public = {k: v for k, v in summary.items() if not k.startswith("_")}
        if delta is not None:
            public["delta"] = delta
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(public, fh, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
