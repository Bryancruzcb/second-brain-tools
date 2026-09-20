"""Run the ops Terraform stacks and the tunnel to the API.

  python deploy/ops.py bootstrap    create the state bucket, once per account
  python deploy/ops.py init         connect deploy/terraform to that bucket
  python deploy/ops.py plan [--up]  preview changes, with the node if --up
  python deploy/ops.py up           apply with the node
  python deploy/ops.py down         apply without the node, everything else stays
  python deploy/ops.py tunnel       forward localhost:8000 to staging's API
                                    (--to prod; --to grafana on localhost:3000)
  python deploy/ops.py deploys      print the deploy history from DynamoDB as TSV
  python deploy/ops.py record-cloud-scorecard --dataset D --vault-dir V
                                    re-score staging and write the gate's card,
                                    with a tunnel open in another window

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
# Each namespace's API service address, pinned in
# deploy/k8s/overlays/<env>/service-ip.yaml, which says why.
SERVICE_IPS = {"staging": "10.43.0.80", "prod": "10.43.0.81"}
# What the tunnel reaches: address, service port, and the local port it
# listens on by default. Grafana's address is pinned in
# deploy/monitoring/grafana.yaml for the same reason as the API's.
TUNNEL_TARGETS = {
    "staging": (SERVICE_IPS["staging"], API_PORT, API_PORT),
    "prod": (SERVICE_IPS["prod"], API_PORT, API_PORT),
    "grafana": ("10.43.0.90", 80, 3000),
}
TERRAFORM_DIR = Path(__file__).resolve().parent / "terraform"
BOOTSTRAP_DIR = TERRAFORM_DIR / "bootstrap"
TFVARS = TERRAFORM_DIR / "terraform.tfvars"
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
# The card the gate compares each deploy against. It sits in k8s/base so
# kustomize generates its ConfigMap next to the canary's card.
CLOUD_SCORECARD = Path(__file__).resolve().parent / "k8s" / "base" / "cloud-scorecard.json"

# One item per deploy, written by the pipeline. deploy/terraform/dynamodb.tf
# creates the table; the item survives `ops.py down`, so the history reads the
# same whether or not the node is running.
DEPLOYS_TABLE = "second-brain-ops-deploys"
# The fields the pipeline writes, in the order `deploys` prints them. Nothing
# outside this list is printed, so a column added to the table later cannot
# reach the terminal until someone names it here.
DEPLOY_COLUMNS = ("sha", "deployed_at", "namespace", "outcome", "hit_rate", "ms_max")
DEPLOY_LIMIT = 20
# What git prints, and enough to find the commit.
SHORT_SHA = 7
MISSING = "-"
# These build a fixed command line of their own, so a flag they don't know is
# a typo rather than something to hand to terraform.
FIXED_COMMANDS = ("tunnel", "deploys", "record-cloud-scorecard")

# Where winget and the AWS CLI installer put the tools when they aren't on PATH.
TERRAFORM_FALLBACK = Path(os.environ.get("LOCALAPPDATA", "")).joinpath(
    "Microsoft",
    "WinGet",
    "Packages",
    "Hashicorp.Terraform_Microsoft.Winget.Source_8wekyb3d8bbwe",
    "terraform.exe",
)
AWS_FALLBACK = Path(r"C:\Program Files\Amazon\AWSCLIV2\aws.exe")
# An activated venv puts its python on PATH and wins, as for every other tool
# here. The fallback is the repo's venv, which is the interpreter that has
# httpx and the backend's own modules; another one stops on the import and
# says which module is missing.
PYTHON_FALLBACK = BACKEND_DIR / "venv" / "Scripts" / "python.exe"


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


def echo(cmd: list[str], cwd: Path | None = None) -> None:
    where = f"  (in {cwd})" if cwd else ""
    print("+ " + subprocess.list2cmdline(cmd) + where, flush=True)


def run(cmd: list[str], cwd: Path | None = None) -> None:
    echo(cmd, cwd)
    code = subprocess.call(cmd, cwd=cwd)
    if code:
        sys.exit(code)


def capture(cmd: list[str]) -> str:
    """Run a command this script reads the output of, instead of showing it."""
    echo(cmd)
    result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True)
    if result.returncode:
        sys.exit(result.returncode)
    return result.stdout


def node_instance_id(main_stack: list[str]) -> str:
    # -json prints null for a stopped node, where -raw would fail.
    instance_id = json.loads(capture(main_stack + ["output", "-json", "node_instance_id"]))
    if not instance_id:
        sys.exit("The node is off. Start it with: python deploy/ops.py up")
    return instance_id


def attribute_text(item: dict, name: str) -> str:
    """One DynamoDB attribute as text, or a dash when the item has no such field.

    Every field the pipeline writes is a string or a number, and the API
    returns both as text under a one-letter type key. An item written before a
    field existed is missing it, and history should still print.
    """
    value = item.get(name) or {}
    text = value.get("S", value.get("N"))
    return MISSING if text is None else text


def deploy_rows(items: list[dict], limit: int) -> list[list[str]]:
    """The newest `limit` deploys, one row of DEPLOY_COLUMNS each.

    The table's partition key is the SHA, so no partition holds the history:
    a query would need a SHA, and a scan comes back in no order. deployed_at
    is an ISO-8601 UTC string, so sorting the text sorts the times. The cut
    comes after the sort, because --limit on the scan would keep an arbitrary
    handful instead of the latest deploys.
    """
    newest_first = sorted(items, key=lambda item: attribute_text(item, "deployed_at"), reverse=True)
    rows = []
    for item in newest_first[:limit]:
        row = [attribute_text(item, name) for name in DEPLOY_COLUMNS]
        row[0] = row[0][:SHORT_SHA]
        rows.append(row)
    return rows


def show_deploys(aws: str, limit: int) -> None:
    """Print the deploy history as TSV, newest first."""
    # --output json because the parse depends on it and a desktop can set
    # another default in ~/.aws/config. --no-cli-pager because the v2 CLI can
    # hand its output to `more` on Windows, and this output is parsed here,
    # not read on screen.
    scan = capture([
        aws, "dynamodb", "scan",
        "--region", REGION,
        "--table-name", DEPLOYS_TABLE,
        "--output", "json",
        "--no-cli-pager",
    ])
    print("\t".join(DEPLOY_COLUMNS))
    for row in deploy_rows(json.loads(scan).get("Items", []), limit):
        print("\t".join(row))


def record_cloud_scorecard(api: str, dataset: str, vault_dir: str, k: int | None) -> None:
    """Score staging through the tunnel and write the card the gate reads.

    This is the one command here that needs `ops.py tunnel` open in another
    window: the eval reaches the API over HTTP, and localhost:8000 is the only
    way to it from the desktop. The dataset and the vault mirror stay here.
    What http_eval writes to the card is a date, the dataset's case count and
    hash, and hit rate, MRR and case counts at one k. No question, no note
    path, which is why the card can live in this public repo.
    """
    python = find_tool("python", PYTHON_FALLBACK)
    cmd = [
        python, "-m", "eval.http_eval",
        "--api", api,
        "--dataset", dataset,
        # Cases whose expected notes the sync refused are ungradable here, and
        # the gate has to be recorded against the same population it scores.
        "--vault-dir", vault_dir,
    ]
    if k is not None:
        # Left out otherwise, so the eval keeps its own default, the backend's
        # configured top k. Two defaults for one number drift apart.
        cmd += ["--k", str(k)]
    cmd += ["--record", str(CLOUD_SCORECARD)]
    # From backend/, the way the canary's card gets recorded: `-m eval.http_eval`
    # imports config and the rest of eval/ from there.
    run(cmd, cwd=BACKEND_DIR)


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
    tunnel.add_argument("--to", "--env", dest="target", choices=sorted(TUNNEL_TARGETS), default="staging",
                        help="an API environment, or grafana")
    tunnel.add_argument("--port", type=int, help="the service's port, if not the target's usual one")
    tunnel.add_argument("--local-port", type=int, help="port on this machine: 8000 for an API, 3000 for grafana")
    deploys = commands.add_parser("deploys", help="print the deploy history as TSV, newest first")
    deploys.add_argument("--limit", type=int, default=DEPLOY_LIMIT,
                         help=f"how many deploys to print (default {DEPLOY_LIMIT})")
    record = commands.add_parser(
        "record-cloud-scorecard",
        help="re-score staging and write the gate's card",
        description="Score staging through an open `ops.py tunnel` and write "
                    f"{CLOUD_SCORECARD.name}, the card the gate compares each deploy "
                    "against. Run it when a change is meant to move retrieval, and "
                    "commit the card. The card holds numbers only: a date, the "
                    "dataset's case count and hash, and hit rate, MRR and case counts.")
    record.add_argument("--api", default=f"http://localhost:{API_PORT}",
                        help="the tunnel's local address (default http://localhost:8000)")
    record.add_argument("--dataset", required=True, help="the private eval set on this desktop (JSONL)")
    record.add_argument("--vault-dir", required=True, help="the staging mirror the vault sync uploads from")
    record.add_argument("--k", type=int, help="cut for hit rate and MRR, if not the backend's own top k")
    return parser.parse_known_args(argv)


def main(argv: list[str] | None = None) -> None:
    args, extra = parse_args(argv)
    if extra and args.action in FIXED_COMMANDS:
        sys.exit(f"{args.action} doesn't take {' '.join(extra)}")

    # Neither of these two touches Terraform, so neither needs it installed.
    if args.action == "deploys":
        show_deploys(find_tool("aws", AWS_FALLBACK), args.limit)
        return
    if args.action == "record-cloud-scorecard":
        record_cloud_scorecard(args.api, args.dataset, args.vault_dir, args.k)
        return

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
        instance_id = node_instance_id(main_stack)
        aws = find_tool("aws", AWS_FALLBACK)
        host, service_port, default_local = TUNNEL_TARGETS[args.target]
        port = args.port or service_port
        local_port = args.local_port or default_local
        run([
            aws, "ssm", "start-session",
            "--region", REGION,
            "--target", instance_id,
            # The API is a ClusterIP service, so nothing listens on the node's
            # own port and the plain port-forwarding document reaches nothing.
            # This one has the agent on the node connect on to the service.
            "--document-name", "AWS-StartPortForwardingSessionToRemoteHost",
            "--parameters",
            f"host={host},portNumber={port},localPortNumber={local_port}",
        ])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        # Ctrl+C is how a tunnel session ends, so skip the traceback.
        sys.exit(130)
