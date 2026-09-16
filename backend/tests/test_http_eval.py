"""The HTTP eval scores what the service serves, and prints numbers only."""
import json

import httpx
import pytest

import main
from fastapi.testclient import TestClient
from eval import http_eval
from tests.test_retrieval import FakeModel, FakeCollection

# Two notes, deterministic order: a.md ranks above b.md for any query.
CANNED = {
    "ids": [["id_a", "id_b"]],
    "documents": [["alpha chunk", "beta chunk"]],
    "metadatas": [[{"source": "a.md", "title": "Alpha"}, {"source": "b.md", "title": "Beta"}]],
    "distances": [[0.1, 0.4]],
}

CASES = [
    {"question": "what did alpha say", "expected_sources": ["a.md"], "scope": "notes"},
    {"question": "what did beta say", "expected_sources": ["b.md"], "scope": "notes"},
]


class Borrowed:
    """Hands main() a client it did not open, so it cannot close it.

    TestClient is an httpx.Client, but entering it runs the app lifespan,
    which loads the embedding model. The eval only needs the routes.
    """

    def __init__(self, inner):
        self.inner = inner

    def __enter__(self):
        return self.inner

    def __exit__(self, *exc):
        return False


@pytest.fixture
def live_api(monkeypatch):
    """The real app behind a real client, with a canned collection."""
    monkeypatch.setattr(main, "model", FakeModel())
    monkeypatch.setattr(main, "chroma_collection", FakeCollection(CANNED))
    monkeypatch.setattr(main, "lexical_index", None)
    return TestClient(main.app)


def test_scores_through_the_served_endpoint(live_api):
    summary = http_eval.score_cases(CASES, client=live_api, base_url="http://testserver", k=8)
    assert summary == {"hit_rate": 1.0, "mrr": pytest.approx(0.75), "cases": 2,
                       "k": 8, "ungradable": 0, "errors": 0}


def test_k_cuts_the_served_list(live_api):
    """At k=1 only the top note counts, so the case expecting b.md misses."""
    summary = http_eval.score_cases(CASES, client=live_api, base_url="http://testserver", k=1)
    assert summary["hit_rate"] == 0.5
    assert summary["cases"] == 2


def test_notes_the_sync_refused_are_ungradable(live_api, tmp_path):
    (tmp_path / "a.md").write_text("alpha", encoding="utf-8")   # b.md stayed home
    summary = http_eval.score_cases(CASES, client=live_api, base_url="http://testserver",
                                    k=8, vault_dir=str(tmp_path))
    assert summary["ungradable"] == 1
    assert summary["cases"] == 1
    assert summary["hit_rate"] == 1.0   # not punished for a note it cannot have


def test_an_unreachable_service_is_an_error_not_a_hit():
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    client = httpx.Client(transport=httpx.MockTransport(refuse))
    http_eval.RETRY_PAUSE_S = 0.0
    summary = http_eval.score_cases(CASES, client=client, base_url="http://testserver", k=8)
    assert summary["errors"] == 2
    assert summary["cases"] == 0
    assert summary["hit_rate"] == 0.0


def test_a_failure_never_prints_the_question(capsys):
    def fail(request):
        return httpx.Response(500, json={"detail": "boom"})

    client = httpx.Client(transport=httpx.MockTransport(fail))
    http_eval.RETRY_PAUSE_S = 0.0
    http_eval.score_cases(CASES, client=client, base_url="http://testserver", k=8)
    err = capsys.readouterr().err
    assert "alpha" not in err and "beta" not in err   # httpx puts the URL in its message
    assert "case 0: HTTPStatusError" in err


def test_cli_prints_one_numbers_only_line(live_api, tmp_path, monkeypatch, capsys):
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("\n".join(json.dumps(c) for c in CASES), encoding="utf-8")
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: Borrowed(live_api))

    assert http_eval.main(["--api", "http://testserver", "--dataset", str(dataset), "--k", "8"]) == 0
    out = capsys.readouterr().out.strip()
    summary = json.loads(out)
    assert summary["hit_rate"] == 1.0
    for case in CASES:
        assert case["question"] not in out
    assert "a.md" not in out


def test_drift_stops_the_gate(live_api, tmp_path, monkeypatch, capsys):
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("\n".join(json.dumps(c) for c in CASES), encoding="utf-8")
    card = tmp_path / "cloud-scorecard.json"
    card.write_text(json.dumps({"metrics": {"hit_rate": 1.0}}), encoding="utf-8")
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: Borrowed(live_api))

    # k=1 serves one note, so one of the two cases misses: 100% -> 50%.
    code = http_eval.main(["--api", "http://testserver", "--dataset", str(dataset),
                           "--k", "1", "--scorecard", str(card)])
    assert code == http_eval.EXIT_DRIFT
    assert "EVAL DRIFT WARNING" in capsys.readouterr().out


def test_record_writes_a_card_with_no_vault_content(live_api, tmp_path, monkeypatch, capsys):
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text("\n".join(json.dumps(c) for c in CASES), encoding="utf-8")
    card = tmp_path / "cloud-scorecard.json"
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: Borrowed(live_api))

    assert http_eval.main(["--api", "http://testserver", "--dataset", str(dataset),
                           "--k", "8", "--record", str(card)]) == 0
    written = card.read_text(encoding="utf-8")
    assert json.loads(written)["metrics"]["hit_rate"] == 1.0
    assert json.loads(written)["dataset"]["cases"] == 2
    for case in CASES:
        assert case["question"] not in written
    assert "a.md" not in written


def test_a_summary_carrying_vault_content_is_refused(monkeypatch, capsys):
    """The print is gated on private_keys_found, not on reviewer discipline."""
    monkeypatch.setattr(http_eval, "score_cases",
                        lambda *a, **k: {"hit_rate": 1.0, "question": "how do I ..."})
    monkeypatch.setattr(http_eval, "load_dataset", lambda path: CASES)
    code = http_eval.main(["--dataset", "ignored"])
    captured = capsys.readouterr()
    assert code == http_eval.EXIT_REFUSED
    assert "how do I" not in captured.out and "how do I" not in captured.err
    assert "question" in captured.err
