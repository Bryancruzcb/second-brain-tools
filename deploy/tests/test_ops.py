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


class Recorder(list):
    """The command lines run() was given. `cwds` holds the directory of each.

    A list, so a test that only cares about the line still compares with one.
    """

    def __init__(self):
        super().__init__()
        self.cwds = []

    def __call__(self, cmd, cwd=None):
        self.append(cmd)
        self.cwds.append(cwd)


@pytest.fixture
def commands(monkeypatch, tmp_path):
    tfvars = tmp_path / "terraform.tfvars"
    tfvars.write_text(f'account_id  = "{ACCOUNT}"\nalert_email = "placeholder"\n', encoding="utf-8")
    monkeypatch.setattr(ops, "TFVARS", tfvars)
    monkeypatch.setattr(ops, "find_tool", lambda name, fallback: name)
    ran = Recorder()
    monkeypatch.setattr(ops, "run", ran)
    return ran


def node_output(monkeypatch, value):
    def fake_run(cmd, **kwargs):
        assert cmd == ["terraform", MAIN, "output", "-json", "node_instance_id"]
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(value))

    monkeypatch.setattr(ops.subprocess, "run", fake_run)


def scan_output(monkeypatch, items):
    """Answer the DynamoDB scan with these items, and record the line it ran."""
    scanned = []

    def fake_run(cmd, **kwargs):
        scanned.append(cmd)
        body = json.dumps({"Items": items, "Count": len(items)})
        return subprocess.CompletedProcess(cmd, 0, stdout=body)

    monkeypatch.setattr(ops.subprocess, "run", fake_run)
    return scanned


def deploy_item(sha, deployed_at, namespace="prod", outcome="deployed", hit_rate="0.85", ms_max="1920"):
    """One item in the shape the API returns: every value under its type key."""
    return {
        "sha": {"S": sha},
        "deployed_at": {"S": deployed_at},
        "namespace": {"S": namespace},
        "outcome": {"S": outcome},
        "hit_rate": {"N": hit_rate},
        "ms_max": {"N": ms_max},
    }


def printed_rows(capsys):
    """The TSV lines, header first. The echoed command line has no tab in it."""
    return [line.split("\t") for line in capsys.readouterr().out.splitlines() if "\t" in line]


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


def test_tunnel_reaches_the_staging_service_through_the_node(commands, monkeypatch):
    """The API is ClusterIP only: forwarding to the node's own port 8000 reached nothing."""
    node_output(monkeypatch, "i-0abc123")
    ops.main(["tunnel"])
    assert commands == [
        [
            "aws", "ssm", "start-session",
            "--region", "us-west-2",
            "--target", "i-0abc123",
            "--document-name", "AWS-StartPortForwardingSessionToRemoteHost",
            "--parameters", "host=10.43.0.80,portNumber=8000,localPortNumber=8000",
        ],
    ]


def test_tunnel_reaches_prod_by_name(commands, monkeypatch):
    node_output(monkeypatch, "i-0abc123")
    ops.main(["tunnel", "--env", "prod"])
    assert commands[0][-1] == "host=10.43.0.81,portNumber=8000,localPortNumber=8000"


def test_tunnel_reaches_grafana_on_a_local_port_of_its_own(commands, monkeypatch):
    node_output(monkeypatch, "i-0abc123")
    ops.main(["tunnel", "--to", "grafana"])
    assert commands[0][-1] == "host=10.43.0.90,portNumber=80,localPortNumber=3000"


def test_to_and_env_are_the_same_option(commands, monkeypatch):
    node_output(monkeypatch, "i-0abc123")
    ops.main(["tunnel", "--to", "prod"])
    ops.main(["tunnel", "--env", "prod"])
    assert commands[0] == commands[1]


def test_grafana_address_matches_its_chart_values():
    grafana = (ops.TERRAFORM_DIR.parent / "monitoring" / "grafana.yaml").read_text(encoding="utf-8")
    assert f"clusterIP: {ops.TUNNEL_TARGETS['grafana'][0]}" in grafana


def test_tunnel_can_listen_on_another_local_port(commands, monkeypatch):
    node_output(monkeypatch, "i-0abc123")
    ops.main(["tunnel", "--local-port", "18000"])
    assert commands[0][-1] == "host=10.43.0.80,portNumber=8000,localPortNumber=18000"


@pytest.mark.parametrize("env", sorted(ops.SERVICE_IPS))
def test_service_ips_match_the_overlays(env):
    """The tunnel's target is only right while the overlay pins the same address."""
    pinned = ops.TERRAFORM_DIR.parent / "k8s" / "overlays" / env / "service-ip.yaml"
    lines = pinned.read_text(encoding="utf-8").splitlines()
    assert f"  clusterIP: {ops.SERVICE_IPS[env]}" in lines


def test_terraform_tunnel_output_names_the_staging_service():
    main_tf = (ops.TERRAFORM_DIR / "main.tf").read_text(encoding="utf-8")
    assert f'staging_service_ip = "{ops.SERVICE_IPS["staging"]}"' in main_tf


def test_tunnel_stops_when_the_node_is_off(commands, monkeypatch):
    node_output(monkeypatch, None)
    with pytest.raises(SystemExit, match="node is off"):
        ops.main(["tunnel"])
    assert commands == []


def test_deploys_scans_the_whole_table(commands, monkeypatch, capsys):
    scanned = scan_output(monkeypatch, [])
    ops.main(["deploys"])
    assert scanned == [
        [
            "aws", "dynamodb", "scan",
            "--region", "us-west-2",
            "--table-name", "second-brain-ops-deploys",
            "--output", "json",
            "--no-cli-pager",
        ],
    ]
    assert printed_rows(capsys) == [list(ops.DEPLOY_COLUMNS)]


def test_deploys_prints_the_newest_first_with_a_short_sha(commands, monkeypatch, capsys):
    scan_output(monkeypatch, [
        deploy_item("b" * 40, "2026-09-18T06:11:03Z", namespace="staging", hit_rate="0.8"),
        deploy_item("a" * 40, "2026-09-19T21:40:12Z"),
    ])
    ops.main(["deploys"])
    assert printed_rows(capsys) == [
        list(ops.DEPLOY_COLUMNS),
        ["a" * 7, "2026-09-19T21:40:12Z", "prod", "deployed", "0.85", "1920"],
        ["b" * 7, "2026-09-18T06:11:03Z", "staging", "deployed", "0.8", "1920"],
    ]


def test_deploys_prints_a_dash_for_a_field_the_item_doesnt_carry(commands, monkeypatch, capsys):
    """An item the pipeline wrote before a field existed still prints as a row."""
    item = deploy_item("c" * 40, "2026-09-17T05:00:00Z", outcome="rolled back")
    del item["ms_max"]
    del item["hit_rate"]
    scan_output(monkeypatch, [item])
    ops.main(["deploys"])
    assert printed_rows(capsys)[1] == ["c" * 7, "2026-09-17T05:00:00Z", "prod", "rolled back", "-", "-"]


def test_deploys_limit_keeps_the_newest_rows_not_the_first_scanned(commands, monkeypatch, capsys):
    """A scan comes back in no order, so the cut has to happen after the sort."""
    scan_output(monkeypatch, [
        deploy_item("1" * 40, "2026-09-01T00:00:00Z"),
        deploy_item("3" * 40, "2026-09-03T00:00:00Z"),
        deploy_item("2" * 40, "2026-09-02T00:00:00Z"),
    ])
    ops.main(["deploys", "--limit", "2"])
    assert [row[0] for row in printed_rows(capsys)[1:]] == ["3" * 7, "2" * 7]


def test_deploys_prints_one_screen_of_history_by_default(commands, monkeypatch, capsys):
    scan_output(monkeypatch, [
        deploy_item(f"{index:040d}", f"2026-09-19T{index:02d}:00:00Z") for index in range(24)
    ])
    ops.main(["deploys"])
    assert len(printed_rows(capsys)) == ops.DEPLOY_LIMIT + 1


def test_record_cloud_scorecard_runs_http_eval_from_the_backend_directory(commands):
    """Like the canary's card: `-m eval.http_eval` resolves config and eval/ from there."""
    ops.main(["record-cloud-scorecard", "--dataset", "eval/dataset.jsonl", "--vault-dir", r"C:\mirror\vault"])
    assert commands == [
        [
            "python", "-m", "eval.http_eval",
            "--api", "http://localhost:8000",
            "--dataset", "eval/dataset.jsonl",
            "--vault-dir", r"C:\mirror\vault",
            "--record", str(ops.CLOUD_SCORECARD),
        ],
    ]
    assert commands.cwds == [ops.BACKEND_DIR]


def test_record_cloud_scorecard_passes_k_only_when_it_is_given(commands):
    """Without it the eval keeps its own default, the backend's configured top k."""
    ops.main(["record-cloud-scorecard", "--dataset", "d.jsonl", "--vault-dir", "v", "--k", "8"])
    assert commands[0][-4:] == ["--k", "8", "--record", str(ops.CLOUD_SCORECARD)]


def test_record_cloud_scorecard_scores_whatever_the_tunnel_serves(commands):
    ops.main(["record-cloud-scorecard", "--dataset", "d.jsonl", "--vault-dir", "v",
              "--api", "http://localhost:18000"])
    assert commands[0][3:5] == ["--api", "http://localhost:18000"]


def test_record_cloud_scorecard_needs_the_dataset_and_the_vault_mirror(commands):
    """Without the mirror every refused note would score as a miss."""
    for argv in (["record-cloud-scorecard"], ["record-cloud-scorecard", "--dataset", "d.jsonl"]):
        with pytest.raises(SystemExit):
            ops.main(argv)
    assert commands == []


def test_the_card_it_records_is_the_file_the_gate_reads():
    gate = (ops.TERRAFORM_DIR.parent / "k8s" / "gate-job.yaml").read_text(encoding="utf-8")
    assert f"/etc/eval/{ops.CLOUD_SCORECARD.name}" in gate
    assert ops.CLOUD_SCORECARD.parent == ops.TERRAFORM_DIR.parent / "k8s" / "base"


def test_the_new_commands_dont_look_for_terraform(commands, monkeypatch):
    """Reading history or scoring staging shouldn't need Terraform installed."""
    asked = []
    monkeypatch.setattr(ops, "find_tool", lambda name, fallback: asked.append(name) or name)
    scan_output(monkeypatch, [])
    ops.main(["deploys"])
    ops.main(["record-cloud-scorecard", "--dataset", "d.jsonl", "--vault-dir", "v"])
    assert asked == ["aws", "python"]


@pytest.mark.parametrize("argv", [
    ["deploys", "--limti", "5"],
    ["record-cloud-scorecard", "--dataset", "d.jsonl", "--vault-dir", "v", "-auto-approve"],
])
def test_the_fixed_commands_refuse_leftover_arguments(commands, argv):
    """Only terraform takes the leftovers; here an unknown flag is a typo."""
    with pytest.raises(SystemExit, match="doesn't take"):
        ops.main(argv)
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


def printing_call(monkeypatch, capsys, calls):
    """Stand in for subprocess.call and keep what was printed before it ran."""
    monkeypatch.setattr(ops.subprocess, "call",
                        lambda cmd, cwd=None: calls.append((capsys.readouterr().out, cwd)) or 0)


def test_run_prints_the_command_before_running_it(monkeypatch, capsys):
    calls = []
    printing_call(monkeypatch, capsys, calls)
    ops.run(["terraform", "-chdir=deploy/terraform", "plan"])
    assert calls == [("+ terraform -chdir=deploy/terraform plan\n", None)]


def test_run_names_the_directory_when_it_runs_somewhere_else(monkeypatch, capsys):
    """record-cloud-scorecard runs from backend/, so the printed line says so."""
    calls = []
    printing_call(monkeypatch, capsys, calls)
    ops.run(["python", "-m", "eval.http_eval"], cwd=ops.BACKEND_DIR)
    assert calls == [(f"+ python -m eval.http_eval  (in {ops.BACKEND_DIR})\n", ops.BACKEND_DIR)]


def test_run_exits_with_the_tool_exit_code(monkeypatch):
    monkeypatch.setattr(ops.subprocess, "call", lambda cmd, cwd=None: 3)
    with pytest.raises(SystemExit) as stopped:
        ops.run(["terraform", "plan"])
    assert stopped.value.code == 3


def test_the_state_bucket_name_matches_both_stacks():
    name = "second-brain-ops-tfstate-${var.account_id}"
    assert name in (ops.BOOTSTRAP_DIR / "main.tf").read_text(encoding="utf-8")
    assert name in (ops.TERRAFORM_DIR / "main.tf").read_text(encoding="utf-8")
    assert ops.state_bucket(ACCOUNT) == f"second-brain-ops-tfstate-{ACCOUNT}"
