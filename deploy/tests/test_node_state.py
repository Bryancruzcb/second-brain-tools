"""The nightly question: is a node running, and should it be?"""
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

import node_state as ns


def test_they_agree_when_the_node_matches_the_variable():
    assert ns.verdict("up", ["i-1"])["agrees"] is True
    assert ns.verdict("down", [])["agrees"] is True


def test_a_forgotten_node_is_the_expensive_disagreement():
    result = ns.verdict("down", ["i-1"])
    assert result["agrees"] is False and result["running"] == 1
    assert "ops.py down" in result["message"]


def test_a_variable_left_up_is_reported_too():
    """deploy.yml skips every run while it looks like this."""
    result = ns.verdict("up", [])
    assert result["agrees"] is False and "skipped" in result["message"]


def test_anything_but_up_counts_as_down():
    for value in ("down", "", "  ", None, "Down ", "paused"):
        assert ns.expected(value) == ns.DOWN
    assert ns.expected(" UP ") == ns.UP
    # So an unset variable with a node running is still caught.
    assert ns.verdict("", ["i-1"])["agrees"] is False


def test_the_month_to_date_total_adds_the_periods_up():
    response = {"ResultsByTime": [
        {"Total": {"UnblendedCost": {"Amount": "3.4567", "Unit": "USD"}}},
        {"Total": {"UnblendedCost": {"Amount": "1.1", "Unit": "USD"}}},
    ]}
    assert ns.month_to_date(response) == 4.56
    assert ns.month_to_date({}) == 0.0


def test_the_window_starts_this_month_and_includes_today():
    """Cost Explorer's end date is exclusive, so today needs tomorrow."""
    assert ns.month_so_far(datetime.date(2026, 9, 19)) == ("2026-09-01", "2026-09-20")
    # And across a month's end.
    assert ns.month_so_far(datetime.date(2026, 9, 30)) == ("2026-09-01", "2026-10-01")


def test_it_fails_the_workflow_only_when_they_disagree(monkeypatch, capsys):
    monkeypatch.setattr(ns, "running_nodes", lambda: ["i-1"])
    monkeypatch.setattr(ns, "spend_so_far", lambda today: 4.12)

    assert ns.main(["--ops-state", "up"]) == 0
    assert ns.main(["--ops-state", "down"]) == 1
    out = capsys.readouterr().out
    assert "month_to_date_usd=4.12" in out and "running=1" in out


def test_the_cost_call_can_be_skipped(monkeypatch, capsys):
    """It charges a cent a call, so a run that only wants the state says so."""
    monkeypatch.setattr(ns, "running_nodes", lambda: [])
    monkeypatch.setattr(ns, "spend_so_far", lambda today: pytest_fail())

    assert ns.main(["--ops-state", "down", "--no-cost"]) == 0
    assert "month_to_date_usd" not in capsys.readouterr().out


def pytest_fail():
    raise AssertionError("Cost Explorer was called with --no-cost")


def test_it_asks_for_the_node_by_tag(monkeypatch):
    seen = {}
    monkeypatch.setattr(ns, "aws", lambda *a: seen.setdefault("args", a) or [])
    ns.running_nodes()
    assert f"Name=tag:Name,Values={ns.NODE_TAG}" in seen["args"]
    # A node mid-boot is a node that is costing money.
    assert "Name=instance-state-name,Values=running,pending" in seen["args"]
