"""ops.py builds terraform and aws command lines, so these tests pin the lines.
run() and subprocess are replaced throughout, so neither tool ever starts.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ops

ACCOUNT = "123456789012"
MAIN = f"-chdir={ops.TERRAFORM_DIR}"
BOOTSTRAP = f"-chdir={ops.BOOTSTRAP_DIR}"


@pytest.fixture
def commands(monkeypatch, tmp_path):
    tfvars = tmp_path / "terraform.tfvars"
    tfvars.write_text(f'account_id  = "{ACCOUNT}"\nalert_email = "placeholder"\n', encoding="utf-8")
    monkeypatch.setattr(ops, "TFVARS", tfvars)
    monkeypatch.setattr(ops, "find_tool", lambda name, fallback: name)
    ran = []
    monkeypatch.setattr(ops, "run", ran.append)
    return ran


def node_output(monkeypatch, value):
    def fake_run(cmd, **kwargs):
        assert cmd == ["terraform", MAIN, "output", "-json", "node_instance_id"]
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(value))

    monkeypatch.setattr(ops.subprocess, "run", fake_run)


def test_bootstrap_inits_then_applies_with_the_account_id(commands):
    ops.main(["bootstrap"])
    assert commands == [
        ["terraform", BOOTSTRAP, "init", "-input=false"],
        ["terraform", BOOTSTRAP, "apply", f"-var=account_id={ACCOUNT}"],
    ]


def test_init_passes_the_state_bucket(commands):
    ops.main(["init"])
    assert commands == [
        ["terraform", MAIN, "init", "-input=false", f"-backend-config=bucket=second-brain-ops-tfstate-{ACCOUNT}"],
    ]


@pytest.mark.parametrize(
    "argv, command",
    [
        (["plan"], ["plan", "-var=node_enabled=false"]),
        (["plan", "--up"], ["plan", "-var=node_enabled=true"]),
        (["up"], ["apply", "-var=node_enabled=true"]),
        (["down"], ["apply", "-var=node_enabled=false"]),
    ],
)
def test_plan_up_and_down_set_node_enabled(commands, argv, command):
    ops.main(argv)
    assert commands == [["terraform", MAIN, *command]]


def test_unknown_arguments_go_to_terraform(commands):
    ops.main(["up", "-auto-approve", "-target=aws_instance.node"])
    assert commands == [
        ["terraform", MAIN, "apply", "-var=node_enabled=true", "-auto-approve", "-target=aws_instance.node"],
    ]


def test_tunnel_forwards_the_api_port_to_the_node(commands, monkeypatch):
    node_output(monkeypatch, "i-0abc123")
    ops.main(["tunnel"])
    assert commands == [
        [
            "aws", "ssm", "start-session",
            "--region", "us-west-2",
            "--target", "i-0abc123",
            "--document-name", "AWS-StartPortForwardingSession",
            "--parameters", "portNumber=8000,localPortNumber=8000",
        ],
    ]


def test_tunnel_can_listen_on_another_local_port(commands, monkeypatch):
    node_output(monkeypatch, "i-0abc123")
    ops.main(["tunnel", "--local-port", "18000"])
    assert commands[0][-1] == "portNumber=8000,localPortNumber=18000"


def test_tunnel_stops_when_the_node_is_off(commands, monkeypatch):
    node_output(monkeypatch, None)
    with pytest.raises(SystemExit, match="node is off"):
        ops.main(["tunnel"])
    assert commands == []


@pytest.mark.parametrize("text", ["", 'account_id = "<12-digit AWS account ID>"\n', 'account_id = "12345"\n'])
def test_bootstrap_and_init_need_a_real_account_id(commands, text):
    ops.TFVARS.write_text(text, encoding="utf-8")
    for action in ("bootstrap", "init"):
        with pytest.raises(SystemExit, match="account_id"):
            ops.main([action])
    assert commands == []


def test_a_missing_tfvars_file_points_at_the_example(commands):
    ops.TFVARS.unlink()
    with pytest.raises(SystemExit, match="terraform.tfvars.example"):
        ops.main(["init"])


def test_find_tool_prefers_path_then_the_install_location(monkeypatch, tmp_path):
    fallback = tmp_path / "terraform.exe"
    monkeypatch.setattr(ops.shutil, "which", lambda name: "/usr/bin/terraform")
    assert ops.find_tool("terraform", fallback) == "/usr/bin/terraform"

    monkeypatch.setattr(ops.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit, match="not on PATH"):
        ops.find_tool("terraform", fallback)

    fallback.write_bytes(b"")
    assert ops.find_tool("terraform", fallback) == str(fallback)


def test_run_prints_the_command_before_running_it(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(ops.subprocess, "call", lambda cmd: calls.append(capsys.readouterr().out) or 0)
    ops.run(["terraform", "-chdir=deploy/terraform", "plan"])
    assert calls == ["+ terraform -chdir=deploy/terraform plan\n"]


def test_run_exits_with_the_tool_exit_code(monkeypatch):
    monkeypatch.setattr(ops.subprocess, "call", lambda cmd: 3)
    with pytest.raises(SystemExit) as stopped:
        ops.run(["terraform", "plan"])
    assert stopped.value.code == 3


def test_the_state_bucket_name_matches_both_stacks():
    name = "second-brain-ops-tfstate-${var.account_id}"
    assert name in (ops.BOOTSTRAP_DIR / "main.tf").read_text(encoding="utf-8")
    assert name in (ops.TERRAFORM_DIR / "main.tf").read_text(encoding="utf-8")
    assert ops.state_bucket(ACCOUNT) == f"second-brain-ops-tfstate-{ACCOUNT}"
