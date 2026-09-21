"""Run one deploy/pipeline script on the node through SSM Run Command.

The pipeline never reaches the cluster directly. The node has no inbound
rules and there is no Ingress, so every step of a deploy is a command handed
to the SSM agent, which runs it as root on the node. This sends one such
command: it puts /opt/sbt at the commit being deployed and then runs the
script, which is why a fresh node needs nothing prepared in advance.

It waits, prints what the script printed, and exits with the script's own
exit code, so a GitHub job step fails exactly when the step failed and the
gate's codes (1 for eval drift, 2 for a refused summary) survive the trip.

Everything printed here comes from the node scripts, which print status
words, counts and SHAs only. The repository is public and the vault is not.

usage:
    python deploy/pipeline/send_command.py --sha <40 hex> \\
        --script deploy/pipeline/deploy-namespace.sh \\
        --timeout 3600 -- staging <sha> second-brain-vault-<account>
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

from output_guard import offenders, refusal

REPO = "https://github.com/Bryancruzcb/second-brain-tools"
# Nothing was printed, so the step failed without saying why in public.
EXIT_REFUSED = 5
# The commit reaches the node inside a shell command, so it is checked here
# as well as in the workflow that passes it.
SHA = re.compile(r"^[0-9a-f]{40}$")
CHECKOUT = "/opt/sbt"
NODE_TAG = "second-brain-ops-node"
POLL_SECONDS = 10
# SSM returns at most 24,000 characters of output inline; the node scripts
# print far less, and the truncation shows up in the printed output.
FINISHED = ("Success", "Failed", "Cancelled", "TimedOut", "Undeliverable", "Terminated")


def bootstrap(sha):
    """Shell that leaves CHECKOUT at sha, on a node that may be brand new."""
    return [
        "set -e",
        f'if [ ! -d {CHECKOUT}/.git ]; then git clone --quiet {REPO} {CHECKOUT}; fi',
        f"git -C {CHECKOUT} fetch --quiet origin",
        f"git -C {CHECKOUT} checkout --quiet --detach --force {sha}",
    ]


def quote(arg):
    """One argument for the node's shell.

    Everything the pipeline passes is a namespace, a SHA or a path, so an
    argument carrying a quote is a mistake or an injection attempt, not
    something to escape and run.
    """
    if "'" in arg:
        raise ValueError(f"argument with a quote in it: {arg!r}")
    return f"'{arg}'"


def command_text(sha, script, args):
    """The one shell command SSM runs: bootstrap, then the script under bash.

    AWS-RunShellScript runs its commands with sh, which on Ubuntu is dash,
    so the script is invoked with bash explicitly.
    """
    if not SHA.match(sha):
        raise ValueError(f"not a commit SHA: {sha!r}")
    quoted = " ".join(quote(a) for a in args)
    return "\n".join(bootstrap(sha) + [f"bash {CHECKOUT}/{script} {quoted}".rstrip()])


def summarize(invocation):
    """(status, exit code, output) from an SSM invocation, stderr included."""
    out = invocation.get("StandardOutputContent", "")
    err = invocation.get("StandardErrorContent", "")
    if err.strip():
        out = f"{out}\n--- stderr\n{err}"
    return invocation.get("Status", "Unknown"), invocation.get("ResponseCode", -1), out


def aws(*args):
    """The AWS CLI, in UTF-8, failing loudly."""
    result = subprocess.run(["aws", "--region", os.environ.get("AWS_REGION", "us-west-2"),
                             "--output", "json", *args],
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            env={**os.environ, "PYTHONUTF8": "1"})
    if result.returncode != 0:
        sys.exit(f"aws {' '.join(args[:2])} failed: {(result.stderr or '').strip()}")
    return json.loads(result.stdout) if (result.stdout or "").strip() else {}


def node_instance_id():
    ids = aws("ec2", "describe-instances",
              "--filters", f"Name=tag:Name,Values={NODE_TAG}",
              "Name=instance-state-name,Values=running",
              "--query", "Reservations[].Instances[].InstanceId")
    if len(ids) != 1:
        sys.exit(f"expected one running node tagged {NODE_TAG}, found {ids}")
    return ids[0]


def run(sha, script, args, timeout, instance_id=None, output_file=None):
    instance_id = instance_id or node_instance_id()
    parameters = json.dumps({"commands": [command_text(sha, script, args)],
                             "executionTimeout": [str(timeout)]})
    sent = aws("ssm", "send-command", "--instance-ids", instance_id,
               "--document-name", "AWS-RunShellScript",
               "--comment", f"deploy {script} {' '.join(args)}"[:100],
               "--parameters", parameters)
    command_id = sent["Command"]["CommandId"]
    print(f"{script} on {instance_id}, command {command_id}", flush=True)

    deadline = time.time() + timeout + 120
    while time.time() < deadline:
        time.sleep(POLL_SECONDS)
        try:
            invocation = aws("ssm", "get-command-invocation",
                             "--command-id", command_id, "--instance-id", instance_id)
        except SystemExit:
            # The invocation is not visible for a moment after send-command.
            continue
        if invocation.get("Status") in FINISHED:
            status, code, output = summarize(invocation)
            # Fail closed, before the print: a public workflow log cannot be
            # taken back, so output that doesn't look like numbers and status
            # words is described rather than shown.
            found = offenders(output)
            if found:
                print(refusal(found), flush=True)
                return EXIT_REFUSED
            if output_file:
                # The next step reads the numbers back out of this.
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(output)
            print(output, end="" if output.endswith("\n") else "\n", flush=True)
            print(f"--- {status} (exit {code})", flush=True)
            if status == "Success" and not code:
                return 0
            # Cancelled and TimedOut carry no exit code of their own.
            return code or 1
    sys.exit(f"timed out after {timeout}s waiting for {command_id}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run a pipeline script on the node over SSM")
    parser.add_argument("--sha", required=True, help="commit the node checks out and deploys")
    parser.add_argument("--script", required=True, help="path under the checkout, e.g. deploy/pipeline/rollback.sh")
    parser.add_argument("--timeout", type=int, default=1800, help="seconds the script may take")
    parser.add_argument("--instance-id", help="skip the lookup, for testing")
    parser.add_argument("--output-file", help="also write the script's output here, for the next step")
    parser.add_argument("args", nargs="*", help="arguments for the script")
    parsed = parser.parse_args(argv)
    return run(parsed.sha, parsed.script, parsed.args, parsed.timeout,
               parsed.instance_id, parsed.output_file)


if __name__ == "__main__":
    sys.exit(main())
