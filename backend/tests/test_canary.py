"""The canary asks a fixed sample, pushes numbers only, and never mistakes an outage for drift."""
import json

import httpx
import pytest
from prometheus_client.parser import text_string_to_metric_families

from eval import canary
from tests.test_http_eval import CASES, Borrowed, live_api  # noqa: F401  (fixture)


def _gauges(text):
    return {f.name: f.samples[0].value for f in text_string_to_metric_families(text)}


def test_the_sample_is_spread_and_fixed():
    cases = list(range(40))
    assert canary.canary_cases(cases, 10) == [0, 4, 8, 12, 16, 20, 24, 28, 32, 36]
    assert canary.canary_cases(cases, 10) == canary.canary_cases(cases, 10)
    assert canary.canary_cases(list(range(10)), 3) == [0, 3, 6]


def test_a_small_set_is_asked_in_full():
    assert canary.canary_cases([1, 2, 3], 10) == [1, 2, 3]
    assert canary.canary_cases([], 10) == []


def test_a_baseline_counts_only_for_the_same_sample():
    fingerprint = {"cases": 40, "sha256": "abc", "canary_cases": 10}
    card = {"dataset": dict(fingerprint), "metrics": {"hit_rate": 0.9}}
    assert canary.baseline_hit_rate(card, fingerprint) == 0.9
    assert canary.baseline_hit_rate(None, fingerprint) is None
    assert canary.baseline_hit_rate(dict(card, dataset={**fingerprint, "sha256": "new"}), fingerprint) is None
    assert canary.baseline_hit_rate(dict(card, dataset={**fingerprint, "canary_cases": 5}), fingerprint) is None


def test_a_clean_run_pushes_the_hit_rate_and_baseline():
    text = canary.exposition({"hit_rate": 0.9, "cases": 10, "errors": 0}, baseline=1.0, now=1700000000.5)
    assert _gauges(text) == {
        "second_brain_canary_cases": 10,
        "second_brain_canary_errors": 0,
        "second_brain_canary_last_run_timestamp_seconds": 1700000000.5,
        "second_brain_canary_hit_rate": 0.9,
        "second_brain_canary_baseline_hit_rate": 1.0,
    }


def test_an_outage_pushes_no_hit_rate():
    """All-error runs score zero; that must raise the error alert, not the drift one."""
    text = canary.exposition({"hit_rate": 0.0, "cases": 0, "errors": 10}, baseline=1.0, now=1.0)
    gauges = _gauges(text)
    assert gauges["second_brain_canary_errors"] == 10
    assert "second_brain_canary_hit_rate" not in gauges
    assert "second_brain_canary_baseline_hit_rate" not in gauges


def test_no_card_means_no_baseline():
    text = canary.exposition({"hit_rate": 1.0, "cases": 10, "errors": 0}, baseline=None, now=1.0)
    assert "second_brain_canary_baseline_hit_rate" not in _gauges(text)


def test_push_replaces_the_namespace_group():
    seen = {}

    def handler(request):
        seen.update(method=request.method, url=str(request.url), body=request.content.decode())
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        canary.push(client, "http://pushgateway:9091/", "staging", "x 1\n")
    assert seen == {"method": "PUT",
                    "url": "http://pushgateway:9091/metrics/job/second-brain-canary/namespace/staging",
                    "body": "x 1\n"}


def _dataset(tmp_path):
    path = tmp_path / "dataset.jsonl"
    path.write_text("\n".join(json.dumps(c) for c in CASES), encoding="utf-8")
    return path


def test_the_cli_records_then_pushes_against_that_card(live_api, tmp_path, monkeypatch, capsys):  # noqa: F811
    dataset, card = _dataset(tmp_path), tmp_path / "canary-card.json"
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: Borrowed(live_api))
    pushed = []
    monkeypatch.setattr(canary, "push", lambda client, gw, ns, body: pushed.append((gw, ns, body)))

    assert canary.main(["--api", "http://testserver", "--dataset", str(dataset), "--k", "8",
                        "--record", str(card)]) == 0
    written = card.read_text(encoding="utf-8")
    assert json.loads(written)["dataset"]["canary_cases"] == 2
    assert pushed == []

    assert canary.main(["--api", "http://testserver", "--dataset", str(dataset), "--k", "8",
                        "--card", str(card), "--pushgateway", "http://pushgateway:9091",
                        "--namespace", "staging"]) == 0
    (gateway, namespace, body), = pushed
    assert (gateway, namespace) == ("http://pushgateway:9091", "staging")
    assert _gauges(body)["second_brain_canary_baseline_hit_rate"] == 1.0
    out = capsys.readouterr().out + written + body
    for case in CASES:
        assert case["question"] not in out
    assert "a.md" not in out


def test_an_unreachable_api_still_pushes_its_errors(tmp_path, monkeypatch):
    def down(request):
        raise httpx.ConnectError("connection refused")

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: real_client(transport=httpx.MockTransport(down)))
    monkeypatch.setattr("eval.http_eval.RETRY_PAUSE_S", 0)
    pushed = []
    monkeypatch.setattr(canary, "push", lambda client, gw, ns, body: pushed.append(body))

    code = canary.main(["--api", "http://api", "--dataset", str(_dataset(tmp_path)),
                        "--pushgateway", "http://pushgateway:9091"])
    assert code == canary.EXIT_REFUSED
    gauges = _gauges(pushed[0])
    assert gauges["second_brain_canary_errors"] == 2
    assert "second_brain_canary_hit_rate" not in gauges


def test_no_card_is_recorded_from_a_failing_run(tmp_path, monkeypatch):
    monkeypatch.setattr(canary, "score_cases",
                        lambda *a, **k: {"hit_rate": 0.0, "mrr": 0.0, "cases": 0, "k": 8,
                                         "ungradable": 0, "errors": 2})
    card = tmp_path / "card.json"
    assert canary.main(["--dataset", str(_dataset(tmp_path)), "--record", str(card)]) == canary.EXIT_REFUSED
    assert not card.exists()


@pytest.mark.parametrize("leak", ["question", "expected_sources"])
def test_a_summary_carrying_vault_content_is_neither_printed_nor_pushed(tmp_path, monkeypatch, capsys, leak):
    monkeypatch.setattr(canary, "score_cases", lambda *a, **k: {"hit_rate": 1.0, "errors": 0, leak: "x"})
    pushed = []
    monkeypatch.setattr(canary, "push", lambda *a: pushed.append(a))
    code = canary.main(["--dataset", str(_dataset(tmp_path)), "--pushgateway", "http://pg"])
    assert code == canary.EXIT_REFUSED
    assert pushed == []
    assert capsys.readouterr().out == ""
