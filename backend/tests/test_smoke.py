"""The smoke test asks a promoted pod seven questions and prints numbers only."""
import httpx
import json

import pytest
from fastapi.testclient import TestClient

import main
from eval import smoke
from tests.test_http_eval import Borrowed

READY_OK = {"ready": True, "index_populated": True,
            "components": {"embedding_model": True, "chroma_collection": True,
                           "lexical_index": True, "reranker": True}}
ONE_RESULT = {"results": [{"title": "Alpha", "id": "a.md", "snippet": "alpha chunk"}]}


def fake_pod(*, ready=READY_OK, ready_status=200, search_status=200,
             results=ONE_RESULT, write_status=403):
    """A stand-in pod: one canned answer per route, each one overridable."""
    def handler(request):
        if request.url.path == smoke.READY_PATH:
            return httpx.Response(ready_status, json=ready)
        if request.url.path == smoke.SEARCH_PATH:
            return httpx.Response(search_status, json=results)
        return httpx.Response(write_status, json={"detail": "Read-only deployment: writes are disabled."})

    return httpx.Client(transport=httpx.MockTransport(handler))


def verdicts(client, base_url="http://api"):
    return {c["name"]: c for c in smoke.run_checks(client, base_url)}


def test_a_serving_pod_passes_every_check():
    checks = smoke.run_checks(fake_pod(), "http://api")
    assert [c["name"] for c in checks] == [
        "ready", "search_0", "search_1", "search_2", "search_3", "search_4", "write_refused"]
    summary = smoke.summarize(checks)
    assert (summary["checks"], summary["passed"], summary["failed"]) == (7, 7, 0)


def test_a_query_with_no_results_fails():
    """A pod on an empty index answers 200 with an empty list, not an error."""
    checks = verdicts(fake_pod(results={"results": []}))
    assert checks["ready"]["ok"] and checks["write_refused"]["ok"]
    assert [name for name, c in checks.items() if name.startswith("search_") and c["ok"]] == []
    assert (checks["search_0"]["status"], checks["search_0"]["results"]) == (200, 0)


def test_a_5xx_fails():
    checks = verdicts(fake_pod(search_status=503, results={}))
    assert checks["search_0"]["ok"] is False
    assert checks["search_0"]["status"] == 503


@pytest.mark.parametrize("status", [200, 422, 404])
def test_a_write_that_is_not_refused_fails(status):
    """200 is a pod running without READ_ONLY; the others are a moved route."""
    checks = verdicts(fake_pod(write_status=status))
    assert checks["write_refused"]["ok"] is False
    assert checks["write_refused"]["status"] == status


def test_a_cold_component_fails_readiness_even_on_a_200():
    """An image older than the strict contract answers 200 whatever its state."""
    cold = {"ready": False, "components": dict(READY_OK["components"], lexical_index=False)}
    checks = verdicts(fake_pod(ready=cold))
    assert checks["ready"]["ok"] is False
    assert (checks["ready"]["components"], checks["ready"]["cold"]) == (4, 1)


def test_a_ready_body_with_no_component_map_fails():
    """all() of an empty map is True, so an answer that says nothing must not pass."""
    assert verdicts(fake_pod(ready={"ready": True}))["ready"]["ok"] is False


def test_an_unreachable_api_fails_without_a_traceback(capsys, monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    client = httpx.Client(transport=httpx.MockTransport(refuse))
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: Borrowed(client))

    assert smoke.main(["--api", "http://api"]) == smoke.EXIT_FAILED
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "ready fail status=0" in captured.out
    assert captured.out.count(" fail ") == 7
    assert '"checks": 7, "failed": 7, "ms_max": 0, "passed": 0' in captured.out


def test_no_query_or_note_text_is_printed(capsys, monkeypatch):
    client = fake_pod()   # built before the patch below takes httpx.Client away
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: Borrowed(client))

    assert smoke.main(["--api", "http://api"]) == 0
    out = capsys.readouterr().out
    for query in smoke.QUERIES:
        assert query not in out
    assert "a.md" not in out and "alpha" not in out
    last = json.loads(out.strip().splitlines()[-1])
    assert (last["checks"], last["passed"], last["failed"]) == (7, 7, 0)


def test_a_check_refuses_a_value_that_is_not_a_number():
    """The numbers-only line is enforced here, not by reviewer discipline."""
    with pytest.raises(TypeError):
        smoke.check("search_0", True, snippet="alpha chunk")
    with pytest.raises(TypeError):
        smoke.check("ready", True, cold=True)


def test_the_checks_read_the_real_routes(monkeypatch):
    """The 403 has to come from deny_when_read_only, not from a canned pod."""
    monkeypatch.setenv("READ_ONLY", "1")
    monkeypatch.setattr(main, "model", None)

    checks = verdicts(TestClient(main.app), "http://testserver")
    assert checks["write_refused"]["ok"] is True
    # The same run on a pod whose models have not loaded fails readiness.
    assert checks["ready"]["ok"] is False
    assert checks["ready"]["status"] == 503
