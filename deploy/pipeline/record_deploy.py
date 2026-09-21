"""Write one item per deploy to DynamoDB, from the numbers the node printed.

Deploy history has to live somewhere that survives `ops.py down`, and it must
not be commits on main: a bot that writes a history file would put a commit on
every deploy and then deploy that commit. So each deploy is one item in
second-brain-ops-deploys, and `python deploy/ops.py deploys` reads them back.

The numbers come from the gate's and the smoke test's own stdout, which is
numbers only by construction (both refuse to print a summary that carries
vault content). This adds nothing to them: it picks the known keys out of the
JSON lines and drops everything else, so a script that starts printing
something new cannot put it in the table by accident.

usage:
    python deploy/pipeline/record_deploy.py --sha <40 hex> --namespace staging \\
        --outcome deployed --from gate.out --from smoke.out
"""
import argparse
import datetime
import json
import sys

from send_command import aws

TABLE = "second-brain-ops-deploys"
# The numbers a deploy is allowed to record. Everything else a script prints
# stays out of the table, whatever it is.
NUMBERS = ("hit_rate", "mrr", "cases", "errors", "ungradable", "checks", "passed", "failed", "ms_max")
# What happened, as `ops.py deploys` prints it.
OUTCOMES = ("deployed", "ungated", "gate-failed", "smoke-failed", "rolled-back")


def json_objects(text):
    """Every line of output that is a JSON object, in order."""
    found = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            found.append(value)
    return found


def metrics(texts):
    """The recordable numbers from several outputs, later ones winning."""
    found = {}
    for text in texts:
        for obj in json_objects(text):
            for key in NUMBERS:
                value = obj.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    found[key] = value
    return found


def item(sha, deployed_at, namespace, outcome, numbers):
    """The DynamoDB item: identity as strings, scores as numbers."""
    attributes = {
        "sha": {"S": sha},
        "deployed_at": {"S": deployed_at},
        "namespace": {"S": namespace},
        "outcome": {"S": outcome},
    }
    for key, value in sorted(numbers.items()):
        attributes[key] = {"N": json.dumps(value)}
    return attributes


def read(path):
    """A step's output, or nothing when the step never ran."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Record one deploy in DynamoDB")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--outcome", required=True, choices=OUTCOMES)
    parser.add_argument("--deployed-at", default=None, help="UTC timestamp; defaults to now")
    parser.add_argument("--from", dest="sources", action="append", default=[],
                        help="a step's output file; missing files are skipped")
    parsed = parser.parse_args(argv)

    record = item(parsed.sha, parsed.deployed_at or now(), parsed.namespace,
                  parsed.outcome, metrics(read(p) for p in parsed.sources))
    aws("dynamodb", "put-item", "--table-name", TABLE, "--item", json.dumps(record))
    print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
