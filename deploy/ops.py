"""Run the ops Terraform stacks and the tunnel to the API.

  python deploy/ops.py bootstrap    create the state bucket, once per account
  python deploy/ops.py init         connect deploy/terraform to that bucket
  python deploy/ops.py plan [--up]  preview changes, with the node if --up
  python deploy/ops.py up           apply with the node
  python deploy/ops.py down         apply without the node, everything else stays
  python deploy/ops.py tunnel       forward localhost:8000 to the API on the node

Arguments ops.py doesn't know go to terraform, so `up -auto-approve` works.
Every command is printed before it runs. This is Python instead of a Makefile
because make runs recipes through cmd or sh depending on PATH, and quoting for
terraform and aws breaks in one or the other.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

REGION = "us-west-2"
API_PORT = 8000
TERRAFORM_DIR = Path(__file__).resolve().parent / "terraform"
BOOTSTRAP_DIR = TERRAFORM_DIR / "bootstrap"
TFVARS = TERRAFORM_DIR / "terraform.tfvars"

# Where winget and the AWS CLI installer put the tools when they aren't on PATH.
TERRAFORM_FALLBACK = Path(os.environ.get("LOCALAPPDATA", "")).joinpath(
    "Microsoft",
    "WinGet",
    "Packages",
    "Hashicorp.Terraform_Microsoft.Winget.Source_8wekyb3d8bbwe",
    "terraform.exe",
)
AWS_FALLBACK = Path(r"C:\Program Files\Amazon\AWSCLIV2\aws.exe")


def find_tool(name: str, fallback: Path) -> str:
    found = shutil.which(name)
    if found:
        return found
    if fallback.is_file():
        return str(fallback)
    sys.exit(f"{name} is not on PATH or at {fallback}")


def read_account_id(tfvars: Path) -> str:
    if not tfvars.is_file():
        sys.exit(f"Missing {tfvars}. Copy terraform.tfvars.example next to it and fill it in.")
    text = tfvars.read_text(encoding="utf-8")
    match = re.search(r'^\s*account_id\s*=\s*"(\d{12})"', text, re.MULTILINE)
    if not match:
        sys.exit(f"No 12-digit account_id in {tfvars}")
    return match.group(1)


def state_bucket(account_id: str) -> str:
    # The same name bootstrap/main.tf gives the bucket.
    return f"second-brain-ops-tfstate-{account_id}"


def echo(cmd: list[str]) -> None:
    print("+ " + subprocess.list2cmdline(cmd), flush=True)


def run(cmd: list[str]) -> None:
    echo(cmd)
    code = subprocess.call(cmd)
    if code:
        sys.exit(code)


def node_instance_id(main_stack: list[str]) -> str:
    # -json prints null for a stopped node, where -raw would fail.
    cmd = main_stack + ["output", "-json", "node_instance_id"]
    echo(cmd)
    result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True)
    if result.returncode:
        sys.exit(result.returncode)
    instance_id = json.loads(result.stdout)
    if not instance_id:
        sys.exit("The node is off. Start it with: python deploy/ops.py up")
    return instance_id


def parse_args(argv: list[str] | None) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        prog="ops.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="action", required=True, metavar="command")
    for name in ("bootstrap", "init", "up", "down"):
        commands.add_parser(name)
    plan = commands.add_parser("plan")
    plan.add_argument("--up", action="store_true", help="plan with the node enabled")
    tunnel = commands.add_parser("tunnel")
    tunnel.add_argument("--port", type=int, default=API_PORT, help="port on the node")
    tunnel.add_argument("--local-port", type=int, help="port on this machine, defaults to --port")
    return parser.parse_known_args(argv)


def main(argv: list[str] | None = None) -> None:
    args, extra = parse_args(argv)
    terraform = find_tool("terraform", TERRAFORM_FALLBACK)
    main_stack = [terraform, f"-chdir={TERRAFORM_DIR}"]

    if args.action == "bootstrap":
        account_id = read_account_id(TFVARS)
        bootstrap = [terraform, f"-chdir={BOOTSTRAP_DIR}"]
        run(bootstrap + ["init", "-input=false"])
        run(bootstrap + ["apply", f"-var=account_id={account_id}", *extra])

    elif args.action == "init":
        bucket = state_bucket(read_account_id(TFVARS))
        run(main_stack + ["init", "-input=false", f"-backend-config=bucket={bucket}", *extra])

    elif args.action == "plan":
        node = "true" if args.up else "false"
        run(main_stack + ["plan", f"-var=node_enabled={node}", *extra])

    elif args.action in ("up", "down"):
        node = "true" if args.action == "up" else "false"
        run(main_stack + ["apply", f"-var=node_enabled={node}", *extra])
        # Otherwise the next merge that touches deploy/terraform undoes this.
        print(f"CI applies follow the OPS_STATE repo variable: gh variable set OPS_STATE --body {args.action}")

    elif args.action == "tunnel":
        if extra:
            sys.exit(f"tunnel doesn't take {' '.join(extra)}")
        instance_id = node_instance_id(main_stack)
        aws = find_tool("aws", AWS_FALLBACK)
        local_port = args.local_port or args.port
        run([
            aws, "ssm", "start-session",
            "--region", REGION,
            "--target", instance_id,
            "--document-name", "AWS-StartPortForwardingSession",
            "--parameters", f"portNumber={args.port},localPortNumber={local_port}",
        ])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Ctrl+C is how a tunnel session ends, so skip the traceback.
        sys.exit(130)
