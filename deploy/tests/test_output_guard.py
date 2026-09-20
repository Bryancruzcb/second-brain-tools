"""The last check before node output reaches a public workflow log."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

import output_guard as og

# Lines the pipeline's scripts actually print.
REAL = """namespace staging sha 4385698aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
checkout 4385698aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
pinned newTag 4385698aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
indexer-first running 120s
deployment "second-brain" successfully rolled out
POD                              IMAGE                                                  READY
second-brain-7d9c8b6f5-4xqzt     ghcr.io/bryancruzcb/second-brain-backend:4385698   true
created eval-gate-4385698aaaaa-x7k2p
{"cases": 40, "errors": 0, "hit_rate": 0.825, "k": 6, "mrr": 0.71, "ungradable": 2}
hit rate 0.825 against 0.825 recorded: no drift
ready pass status=200 components=4 cold=0 ms=412
{"checks": 7, "failed": 0, "ms_max": 1940, "passed": 7}
rolled back to 94b1e79aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
"""


def test_a_real_deploy_prints_nothing_the_guard_objects_to():
    assert og.offenders(REAL) == []


def test_a_note_path_stops_the_print():
    text = REAL + "expected source vault/Projects/Second Brain.md\n"
    found = og.offenders(text)
    assert len(found) == 1 and ".md" in found[0][1]


def test_case_does_not_help():
    assert og.suspicious("kept NOTE.MD") is not None


def test_a_summary_carrying_a_string_stops_the_print():
    """Both summaries are numbers; a string in one means something else got in."""
    reason = og.suspicious('{"hit_rate": 0.8, "worst_case": "why did I leave that job"}')
    assert reason is not None and "worst_case" in reason


def test_a_json_line_that_does_not_parse_stops_the_print():
    assert og.suspicious('{"hit_rate": 0.8, ') is not None


def test_non_ascii_stops_the_print():
    assert og.suspicious("note: café plans") == "not plain ASCII"


def test_a_very_long_line_stops_the_print():
    assert og.suspicious("x" * (og.MAX_LINE + 1)) is not None
    assert og.suspicious("x" * og.MAX_LINE) is None


def test_the_refusal_says_where_it_tripped_and_not_what_it_said():
    secret = "vault/Health/therapy notes.md"
    found = og.offenders(f"fine 1\n{secret}\n")
    message = og.refusal(found)
    assert secret not in message and "therapy" not in message
    assert "line 2" in message and ".md" in message


def test_the_guard_runs_before_the_print(monkeypatch, capsys, tmp_path):
    """send_command prints nothing at all when the output trips it."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
    import send_command as sc

    monkeypatch.setattr(sc, "aws", lambda *a: (
        {"Command": {"CommandId": "cmd-1"}} if a[:2] == ("ssm", "send-command")
        else {"Status": "Success", "ResponseCode": 0,
              "StandardOutputContent": "vault/Health/therapy notes.md\n",
              "StandardErrorContent": ""}))
    monkeypatch.setattr(sc.time, "sleep", lambda _: None)

    path = tmp_path / "gate.out"
    code = sc.run("4385698" + "a" * 33, "deploy/pipeline/run-job.sh", ["staging"], 60,
                  instance_id="i-0abc", output_file=str(path))

    out = capsys.readouterr().out
    assert code == sc.EXIT_REFUSED
    assert "therapy" not in out and "REFUSING" in out
    # Not written either: a later step would print it.
    assert not path.exists()
