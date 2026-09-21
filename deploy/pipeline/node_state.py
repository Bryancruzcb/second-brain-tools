"""Does a node exist, and does OPS_STATE say one should?

The node is the only part of this that costs real money, and it is meant to
exist only while Bryan is working: `ops.py up` before, `ops.py down` after,
with the repo variable OPS_STATE kept in step so that terraform.yml's apply
on main does not put the node back. A forgotten node is the one mistake here
that can run for a month, so nightly-cost.yml asks this question every night
and opens an issue when the two answers disagree.

The disagreement goes both ways. A node running while OPS_STATE says down is
the expensive one. OPS_STATE saying up with no node is the cheap one, and
worth the same issue: deploy.yml skips every run while it looks like that,
so deploys would silently stop happening.

usage:
    python deploy/pipeline/node_state.py --ops-state "$OPS_STATE"
"""
import argparse
import datetime
import sys

from send_command import NODE_TAG, aws

UP, DOWN = "up", "down"


def expected(ops_state):
    """OPS_STATE as one of two states. Anything but 'up' means no node."""
    return UP if (ops_state or "").strip().lower() == UP else DOWN


def verdict(ops_state, running):
    """Whether the account matches OPS_STATE, and the line that says so."""
    want = expected(ops_state)
    actual = UP if running else DOWN
    if want == actual:
        return {"agrees": True, "ops_state": want, "running": len(running),
                "message": f"OPS_STATE is {want} and {len(running)} node(s) are running"}
    if actual == UP:
        message = (f"OPS_STATE is {want} but {len(running)} node(s) are running: "
                   "run `python deploy/ops.py down`, or set OPS_STATE to up")
    else:
        message = ("OPS_STATE is up but no node is running: deploys are being "
                   "skipped. Run `python deploy/ops.py up`, or set OPS_STATE to down")
    return {"agrees": False, "ops_state": want, "running": len(running), "message": message}


def month_to_date(response):
    """Unblended USD so far this month, from a Cost Explorer response."""
    total = 0.0
    for period in response.get("ResultsByTime", []):
        total += float(period.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0.0))
    return round(total, 2)


def month_so_far(today):
    """(first of this month, tomorrow) as Cost Explorer wants them.

    The end is exclusive, so tomorrow is what includes today.
    """
    return today.replace(day=1).isoformat(), (today + datetime.timedelta(days=1)).isoformat()


def running_nodes():
    return aws("ec2", "describe-instances",
               "--filters", f"Name=tag:Name,Values={NODE_TAG}",
               "Name=instance-state-name,Values=running,pending",
               "--query", "Reservations[].Instances[].InstanceId")


def spend_so_far(today):
    start, end = month_so_far(today)
    return month_to_date(aws("ce", "get-cost-and-usage",
                             "--time-period", f"Start={start},End={end}",
                             "--granularity", "MONTHLY", "--metrics", "UnblendedCost"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare OPS_STATE with the running node")
    parser.add_argument("--ops-state", default="", help="the OPS_STATE repo variable")
    parser.add_argument("--no-cost", action="store_true",
                        help="skip Cost Explorer, which charges a cent a call")
    parsed = parser.parse_args(argv)

    result = verdict(parsed.ops_state, running_nodes())
    if not parsed.no_cost:
        result["month_to_date_usd"] = spend_so_far(datetime.date.today())
    for key in ("ops_state", "running", "month_to_date_usd"):
        if key in result:
            print(f"{key}={result[key]}")
    print(result["message"])
    return 0 if result["agrees"] else 1


if __name__ == "__main__":
    sys.exit(main())
