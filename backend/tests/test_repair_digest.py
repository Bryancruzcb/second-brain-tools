"""scripts/repair_digest.py: the weekly Repair digest must stay read-only.

The script is not a package, so it is loaded from its path. A real HTTP server
on an ephemeral port stands in for the backend and records every request, so
"only GET /api/health" is asserted on the wire, not by reading the code.
"""
import hashlib
import http.server
import importlib.util
import json
import os
import socket
import threading
import time

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load():
    path = os.path.join(REPO_ROOT, "scripts", "repair_digest.py")
    spec = importlib.util.spec_from_file_location("repair_digest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rd = _load()

HEALTH = {
    "total_notes": 12,
    "total_links": 30,
    "avg_links_per_note": 2.5,
    "broken_links": [
        {"source": "A.md", "source_title": "A", "target": "Missing One"},
        {"source": "B.md", "source_title": "B", "target": "Missing Two"},
    ],
    "orphaned_notes": [{"path": "Lonely.md", "title": "Lonely"}],
    "tagless_notes": [{"path": "Bare.md", "title": "Bare", "suggestions": ["#coding", "#school"]}],
    "nodes": [{"id": "A.md"}],
    "edges": [],
}


@pytest.fixture
def backend():
    seen = []
    last_scan = time.time() - 3600

    class Handler(http.server.BaseHTTPRequestHandler):
        def _record(self):
            seen.append(f"{self.command} {self.path}")

        def do_GET(self):  # noqa: N802
            self._record()
            if self.path != "/api/health":
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps({"data": HEALTH, "is_scanning": False, "last_scan_time": last_scan}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):  # noqa: N802
            self._record()
            self.send_response(500)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", seen
    server.shutdown()
    server.server_close()


def _closed_port_url():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def test_api_digest_only_issues_get_api_health(backend, tmp_path):
    url, seen = backend
    out, js = tmp_path / "d.md", tmp_path / "d.json"
    rc = rd.main(["--url", url, "--source", "api", "--out", str(out), "--json-out", str(js),
                  "--cache-file", str(tmp_path / "none.json")])
    assert rc == 0
    assert seen == ["GET /api/health"]
    md = out.read_text(encoding="utf-8")
    assert "| Broken links | 2 |" in md
    assert "| Orphaned notes | 1 |" in md
    assert "| Tagless notes | 1 |" in md
    assert "| **To fix** | **4** |" in md
    assert "`A` links to missing `Missing One`" in md
    assert "suggested: #coding, #school" in md
    assert "Stale" not in md
    summary = json.loads(js.read_text(encoding="utf-8"))
    assert summary["counts"] == {"broken_links": 2, "orphaned_notes": 1, "tagless_notes": 1}
    assert summary["stale"] is False
    assert "_items" not in summary


def test_falls_back_to_cache_file_without_modifying_it(tmp_path, capsys):
    cache = tmp_path / "health_cache.json"
    cache.write_text(json.dumps(HEALTH), encoding="utf-8")
    before_hash, before_mtime = _sha(cache), os.path.getmtime(cache)
    rc = rd.main(["--url", _closed_port_url(), "--cache-file", str(cache)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "falling back" in captured.err
    assert "| **To fix** | **4** |" in captured.out
    assert _sha(cache) == before_hash
    assert os.path.getmtime(cache) == before_mtime


def test_no_source_reachable_exits_2(tmp_path):
    assert rd.main(["--url", _closed_port_url(), "--source", "api"]) == 2
    assert rd.main(["--source", "cache", "--cache-file", str(tmp_path / "missing.json")]) == 2


def test_old_scan_is_flagged_stale():
    snap = {"source": "x", "data": HEALTH, "is_scanning": False, "last_scan_time": time.time() - 10 * 86400}
    s = rd.summarize(snap, stale_days=7)
    assert s["stale"] is True
    assert "**Stale:**" in rd.render_markdown(s, stale_days=7)
    never = rd.summarize({"source": "x", "data": {}, "is_scanning": False, "last_scan_time": 0})
    assert never["stale"] is True and never["last_scan_time"] is None


def test_week_over_week_diff(backend, tmp_path):
    url, _ = backend
    prev = tmp_path / "prev.json"
    prev.write_text(json.dumps({
        "counts": {"broken_links": 3, "orphaned_notes": 1, "tagless_notes": 0},
        "keys": {
            "broken_links": ["A.md -> Missing One", "Old.md -> Gone"],
            "orphaned_notes": ["Lonely.md"],
            "tagless_notes": [],
        },
    }), encoding="utf-8")
    out, js = tmp_path / "d.md", tmp_path / "d.json"
    assert rd.main(["--url", url, "--out", str(out), "--json-out", str(js), "--previous", str(prev)]) == 0
    md = out.read_text(encoding="utf-8")
    assert "| Broken links | 2 | -1 (was 3) |" in md
    assert "- Broken links: 1 new, 1 resolved" in md
    assert "new: `B.md -> Missing Two`" in md
    delta = json.loads(js.read_text(encoding="utf-8"))["delta"]
    assert delta["broken_links"]["resolved"] == ["Old.md -> Gone"]
    assert delta["tagless_notes"]["new"] == ["Bare.md"]


def test_refuses_to_write_inside_vault_or_over_cache(backend, tmp_path, monkeypatch):
    url, seen = backend
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    assert rd.main(["--url", url, "--out", str(vault / "00 Home" / "digest.md")]) == 2
    cache = tmp_path / "health_cache.json"
    cache.write_text("{}", encoding="utf-8")
    assert rd.main(["--url", url, "--cache-file", str(cache), "--json-out", str(cache)]) == 2
    assert cache.read_text(encoding="utf-8") == "{}"
    assert list(vault.iterdir()) == []
    assert seen == []  # refused before any request


def test_limit_truncates_lists():
    many = dict(HEALTH, orphaned_notes=[{"path": f"N{i}.md", "title": f"N{i}"} for i in range(30)])
    s = rd.summarize({"source": "x", "data": many, "is_scanning": False, "last_scan_time": time.time()})
    md = rd.render_markdown(s, limit=5)
    assert "## Orphaned notes (30)" in md
    assert "...and 25 more" in md


def test_previous_and_json_out_can_be_the_same_rolling_file(backend, tmp_path):
    url, _ = backend
    rolling = tmp_path / "latest.json"
    assert rd.main(["--url", url, "--out", str(tmp_path / "w1.md"), "--json-out", str(rolling), "--previous", str(rolling)]) == 0
    assert rd.main(["--url", url, "--out", str(tmp_path / "w2.md"), "--json-out", str(rolling), "--previous", str(rolling)]) == 0
    md2 = (tmp_path / "w2.md").read_text(encoding="utf-8")
    assert "| Broken links | 2 | +0 (was 2) |" in md2
    assert "- Broken links: 0 new, 0 resolved" in md2
