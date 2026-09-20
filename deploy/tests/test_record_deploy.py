"""The deploy record: numbers from the node's output, nothing else."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

import record_deploy as rd

GATE = """
deploying eval-gate-7x2kd
{"cases": 40, "errors": 0, "hit_rate": 0.825, "k": 6, "mrr": 0.71, "ungradable": 2}
hit rate 0.825 against 0.825 recorded: no drift
"""
SMOKE = '{"checks": 7, "failed": 0, "ms_max": 1940, "passed": 7}\n'


def test_it_takes_the_numbers_out_of_the_output():
    assert rd.metrics([GATE, SMOKE]) == {"cases": 40, "errors": 0, "hit_rate": 0.825,
                                         "mrr": 0.71, "ungradable": 2, "checks": 7,
                                         "failed": 0, "ms_max": 1940, "passed": 7}


def test_prose_and_unknown_keys_stay_out():
    """The table records scores, not whatever a script decides to print."""
    text = '{"hit_rate": 0.8, "note": "vault/private note.md", "k": 6, "ok": true}'
    assert rd.metrics([text]) == {"hit_rate": 0.8}


def test_a_later_output_wins():
    assert rd.metrics(['{"hit_rate": 0.1}', '{"hit_rate": 0.9}'])["hit_rate"] == 0.9


def test_output_with_no_json_records_no_numbers():
    assert rd.metrics(["rollout restarted\nrolled back to revision 3\n"]) == {}
    assert rd.metrics(["{not json}", "[1, 2]", ""]) == {}


def test_the_item_types_identity_as_strings_and_scores_as_numbers():
    record = rd.item("abc123", "2026-09-19T21:00:00Z", "prod", "deployed",
                     {"hit_rate": 0.825, "cases": 40})
    assert record["sha"] == {"S": "abc123"}
    assert record["deployed_at"] == {"S": "2026-09-19T21:00:00Z"}
    assert record["namespace"] == {"S": "prod"} and record["outcome"] == {"S": "deployed"}
    # DynamoDB numbers travel as strings; an int must not arrive as 40.0.
    assert record["hit_rate"] == {"N": "0.825"} and record["cases"] == {"N": "40"}


def test_a_failed_deploy_records_the_score_that_failed_it(tmp_path, monkeypatch):
    gate = tmp_path / "gate.out"
    gate.write_text('{"hit_rate": 0.55, "cases": 40, "errors": 0}\n', encoding="utf-8")
    sent = {}
    monkeypatch.setattr(rd, "aws", lambda *a: sent.update(args=a) or {})

    assert rd.main(["--sha", "abc123", "--namespace", "staging", "--outcome", "gate-failed",
                    "--deployed-at", "2026-09-19T21:00:00Z", "--from", str(gate),
                    "--from", str(tmp_path / "smoke.out")]) == 0

    args = sent["args"]
    assert args[:4] == ("dynamodb", "put-item", "--table-name", rd.TABLE)
    record = json.loads(args[-1])
    assert record["outcome"] == {"S": "gate-failed"} and record["hit_rate"] == {"N": "0.55"}
    # The smoke test never ran, so its file is missing rather than empty.
    assert "ms_max" not in record


def test_an_unknown_outcome_is_refused():
    with pytest.raises(SystemExit):
        rd.main(["--sha", "abc", "--namespace", "staging", "--outcome", "fine"])


def test_the_timestamp_it_writes_sorts(monkeypatch):
    """deployed_at is the range key, so the string order is the time order."""
    stamp = rd.now()
    assert len(stamp) == 20 and stamp.endswith("Z") and stamp[10] == "T"
