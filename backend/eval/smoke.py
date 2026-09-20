"""Seven fixed checks against a promoted deployment, printed as numbers only.

The gate (eval/http_eval.py) scores staging before the promotion. After the
image reaches prod nothing had asked prod itself whether it serves: a rollout
can go Ready on a pod whose index is empty or whose write guard is off, and
the next thing that would notice is the canary, up to 15 minutes later.

PLAN.md section 6.4 step 4 asks for five fixed queries against /api/search,
one search_vault call through mcp_server.py, and one write that must return
403. The middle one cannot run here. mcp_server.py is deliberately kept out
of the API image: its SDK lives in backend/requirements-mcp.txt so that the
backend container does not carry it (that file's comment says so), and this
runs inside that image. So in its place this checks the two endpoints
search_vault itself calls, in the order it calls them: GET /api/ready, which
the MCP client reads before searching and which must report every component
loaded, and then GET /api/search. Anything that would break search_vault at
the HTTP level breaks one of those two.

What it prints is a check name, pass or fail, and numbers: status codes,
result counts, milliseconds. The queries travel in a query string and never
into stdout, and neither do httpx exceptions, which carry the request URL and
so the query with it. An API that is not there is status 0 and a failed
check, not a traceback: a smoke test that crashes reads like one that never
ran, and this one decides whether the deploy stays.

Usage, in the cluster (deploy/k8s/smoke-job.yaml, created per deploy):
    python -m eval.smoke --api http://second-brain:8000
and from the desktop through `ops.py tunnel --env prod --local-port 8001`:
    python -m eval.smoke --api http://localhost:8001
"""
import argparse
import json
import sys
import time

import httpx

READY_PATH = "/api/ready"
SEARCH_PATH = "/api/search"
WRITE_PATH = "/api/note/create"

# Generic on purpose: this repository is public, so the five queries carry
# nothing from the vault. They do not have to be good questions. /api/search
# returns the nearest chunks for any non-empty query, so an empty result set
# means the index or a retrieval leg is gone, which is what this looks for.
# Whether the right notes come back is the gate's measurement, not this one.
QUERIES = (
    "project notes",
    "what did I decide",
    "python example",
    "meeting summary",
    "how does this work",
)

# The scope the frontend and the MCP client default to. A scope whose
# category happens to be empty in this vault copy would return nothing for a
# reason that is not a bad deploy.
SCOPE = "notes"

# A body /api/note/create would accept if the pod were writable, so each
# outcome means one thing: 403 is deny_when_read_only, 200 is a pod running
# without READ_ONLY, anything else is the route having moved. A body the
# route would reject answers 403 here too (the dependency runs before body
# validation, pinned by tests/test_read_only.py) but answers 422 on a
# writable pod, which reads the same as a schema change. The cost of the
# valid body is that a wrongly writable pod ends up with one known file in
# its own vault copy, which is a copy of S3 that never syncs back, and that
# only happens on a deploy this check then fails and rolls back.
WRITE_BODY = {"title": "deploy smoke check", "content": ""}

EXIT_FAILED = 1


def check(name, ok, **numbers):
    """One check as a name, a verdict and numbers.

    The numbers are read off a response as counts and status codes, never
    copied out of a body. This refuses a value that is not a number so a
    later edit cannot quietly put a snippet or a note path on the line.
    """
    bad = sorted(k for k, v in numbers.items()
                 if isinstance(v, bool) or not isinstance(v, (int, float)))
    if bad:
        raise TypeError(f"check values must be numbers: {', '.join(bad)}")
    return dict(name=name, ok=bool(ok), **numbers)


def ready_verdict(status, body, ms):
    """200 from ?strict=1, with a component map and nothing still cold.

    strict=1 already answers 503 until every component has loaded and the
    index holds chunks, so the map is a second reading of the same fact.
    It is worth reading: an image older than the strict contract answers 200
    whatever its state, and the map is what the MCP client and the frontend
    decide on, so this checks what they would see.
    """
    components = (body or {}).get("components") or {}
    cold = [name for name, loaded in components.items() if not loaded]
    ok = status == 200 and bool(components) and not cold
    return check("ready", ok, status=status, components=len(components),
                 cold=len(cold), ms=ms)


def search_verdict(index, status, body, ms):
    """200 with at least one result. The query is named by position only."""
    results = len((body or {}).get("results") or [])
    return check(f"search_{index}", status == 200 and results > 0,
                 status=status, results=results, ms=ms)


def write_verdict(status, ms):
    """The one write has to be refused by the read-only guard."""
    return check("write_refused", status == 403, status=status, ms=ms)


def summarize(checks):
    passed = sum(1 for c in checks if c["ok"])
    return {"checks": len(checks), "passed": passed, "failed": len(checks) - passed,
            "ms_max": max((c["ms"] for c in checks), default=0)}


def format_check(c):
    numbers = " ".join(f"{k}={v}" for k, v in c.items() if k not in ("name", "ok"))
    return f"{c['name']} {'pass' if c['ok'] else 'fail'} {numbers}"


def format_summary(summary):
    """The last line, as JSON: the pipeline reads its numbers back out of it.

    http_eval prints its summary the same way, and deploy/pipeline/record_deploy.py
    picks the known keys out of both and writes them to the deploy record.
    """
    return json.dumps(summary, sort_keys=True)


def send(client, method, url, **kwargs):
    """(status, decoded body, elapsed ms), with no exception left to print.

    A refused connection, a timeout and a body that is not JSON are all
    conditions this reports rather than raises: status 0 or a body of None
    fails the check that asked for them, and the exception, which holds the
    request URL and so the query, goes no further than here.
    """
    start = time.monotonic()
    status, body = 0, None
    try:
        response = client.request(method, url, **kwargs)
        status = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = None
    except httpx.HTTPError:
        pass
    return status, body, round((time.monotonic() - start) * 1000)


def run_checks(client, base_url):
    """Readiness, the five queries, then the write, in that order.

    The first two are the order search_vault uses. Every check runs even
    after one fails: which ones failed together is what says whether the pod
    is cold, empty, or serving with its write guard off.
    """
    base = base_url.rstrip("/")

    status, body, ms = send(client, "GET", base + READY_PATH, params={"strict": 1})
    checks = [ready_verdict(status, body, ms)]

    for index, query in enumerate(QUERIES):
        status, body, ms = send(client, "GET", base + SEARCH_PATH,
                                params={"q": query, "scope": SCOPE})
        checks.append(search_verdict(index, status, body, ms))

    status, _, ms = send(client, "POST", base + WRITE_PATH, json=WRITE_BODY)
    checks.append(write_verdict(status, ms))
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check a promoted deployment through its own API")
    parser.add_argument("--api", default="http://localhost:8000",
                        help="base URL of the service to check")
    # One timeout for the client covers the connect phase too, for a pod that
    # is up but not yet serving. Staging measured p95 1.92 s for a search.
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)

    with httpx.Client(timeout=args.timeout) as client:
        checks = run_checks(client, args.api)

    for c in checks:
        print(format_check(c))
    summary = summarize(checks)
    print(format_summary(summary))
    return EXIT_FAILED if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
