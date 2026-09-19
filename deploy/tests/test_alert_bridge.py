"""The alert bridge: one GitHub issue per alert and namespace, and nothing private in it."""
import io
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "monitoring"))

import alert_bridge as bridge
from alert_bridge import Close, Comment, Create


def payload(status="firing", **extra_labels):
    labels = {"alertname": "ApiNotReady", "namespace": "staging", "severity": "critical", **extra_labels}
    return {
        "status": status,
        "groupLabels": {"alertname": "ApiNotReady", "namespace": "staging"},
        "alerts": [{
            "status": status,
            "labels": labels,
            "annotations": {"summary": "The API in staging has had fewer ready replicas than it asks for, for 5 minutes."},
            "startsAt": "2026-09-19T20:00:00Z",
        }],
    }


def test_the_title_names_the_alert_and_namespace():
    assert bridge.issue_title(payload()) == "Alert: ApiNotReady in staging"
    assert bridge.issue_title({"groupLabels": {"alertname": "DiskAlmostFull"}}) == "Alert: DiskAlmostFull"
    assert bridge.issue_title({}) == "Alert: unknown"


@pytest.mark.parametrize("status, open_issue, expected", [
    ("firing", None, [Create]),
    ("firing", 7, [Comment]),
    ("resolved", 7, [Comment, Close]),
    ("resolved", None, []),
])
def test_the_plan_follows_the_alert_and_the_open_issue(status, open_issue, expected):
    actions = bridge.plan(payload(status), open_issue)
    assert [type(a) for a in actions] == expected
    assert all(a.number == 7 for a in actions if not isinstance(a, Create))


def test_only_allowed_labels_and_the_summary_reach_github():
    """The repository is public: anything a label or annotation might carry stays out."""
    p = payload(pod="second-brain-6568bc68f7-d6cm6", note="Private Note.md")
    p["alerts"][0]["annotations"]["description"] = "text from a private note"
    create, = bridge.plan(p, None)
    for text in (create.title, create.body, bridge.comment_body(p)):
        assert "Private Note" not in text
        assert "second-brain-6568bc68f7" not in text
        assert "text from a private note" not in text
    assert "severity=critical" in create.body


def test_a_long_or_multiline_summary_is_collapsed_and_cut():
    p = payload()
    p["alerts"][0]["annotations"]["summary"] = "line one\n\nline   two " + "x" * 1000
    line, = bridge.alert_lines(p)
    summary = line.split(": ", 1)[1]
    assert "\n" not in summary and "line one line two" in summary
    assert len(summary) == bridge.SUMMARY_LIMIT and summary.endswith("…")


class FakeGitHub:
    """Keeps issues in memory, the way GitHub would."""

    def __init__(self):
        self.issues, self.comments, self.next_number = {}, [], 1

    def open_issue(self, title):
        return next((n for n, i in self.issues.items() if i["title"] == title and i["open"]), None)

    def apply(self, action):
        match action:
            case Create(title, body):
                self.issues[self.next_number] = {"title": title, "body": body, "open": True}
                self.next_number += 1
            case Comment(number, body):
                self.comments.append((number, body))
            case Close(number):
                self.issues[number]["open"] = False


def test_repeats_comment_on_one_issue_and_the_resolve_closes_it():
    github, log = FakeGitHub(), []
    bridge.handle(payload("firing"), github, log.append)
    bridge.handle(payload("firing"), github, log.append)   # Alertmanager's repeat, or a retry
    assert len(github.issues) == 1 and len(github.comments) == 1
    bridge.handle(payload("resolved"), github, log.append)
    assert github.issues[1]["open"] is False
    assert github.comments[-1][1].startswith("Resolved.")
    # A second firing after the resolve opens a fresh issue rather than reusing the closed one.
    bridge.handle(payload("firing"), github, log.append)
    assert len(github.issues) == 2


def test_without_a_token_it_only_logs():
    log = []
    bridge.handle(payload(), None, log.append)
    assert log == ["no token, would handle firing for 'Alert: ApiNotReady in staging'"]


def test_the_token_file_is_optional(tmp_path):
    assert bridge.read_token(tmp_path / "missing") is None
    (tmp_path / "empty").write_text("\n", encoding="utf-8")
    assert bridge.read_token(tmp_path / "empty") is None
    (tmp_path / "token").write_text("github_pat_x\n", encoding="utf-8")
    assert bridge.read_token(tmp_path / "token") == "github_pat_x"


class Recorded:
    def __init__(self, body=b""):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_github_requests(monkeypatch):
    sent = []

    def urlopen(request, timeout):
        sent.append((request.get_method(), request.full_url, request.data, dict(request.header_items())))
        if request.get_method() == "GET":
            return Recorded(json.dumps([
                {"number": 3, "title": "Alert: ApiNotReady in staging", "pull_request": {}},
                {"number": 4, "title": "Alert: ApiNotReady in staging"},
            ]).encode())
        return Recorded()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    github = bridge.GitHub("owner/repo", "tok")
    assert github.open_issue("Alert: ApiNotReady in staging") == 4   # a pull request never matches
    github.apply(Create("t", "b"))
    github.apply(Comment(4, "c"))
    github.apply(Close(4))

    methods = [(m, u.removeprefix("https://api.github.com/repos/owner/repo")) for m, u, _, _ in sent]
    assert methods == [("GET", "/issues?labels=alert&state=open&per_page=100"),
                       ("POST", "/issues"), ("POST", "/issues/4/comments"), ("PATCH", "/issues/4")]
    assert json.loads(sent[1][2]) == {"title": "t", "body": "b", "labels": ["alert"]}
    assert json.loads(sent[3][2]) == {"state": "closed", "state_reason": "completed"}
    assert sent[1][3]["Authorization"] == "Bearer tok"


@pytest.fixture
def server():
    calls = []

    class Flaky:
        """Opens nothing; fails when told to, like GitHub being unreachable."""
        fail = False

        def open_issue(self, title):
            if Flaky.fail:
                raise urllib.error.URLError("down")
            return None

        def apply(self, action):
            calls.append(action)

    httpd = HTTPServer(("127.0.0.1", 0), bridge.make_handler(Flaky(), lambda m: None))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}", calls, Flaky
    httpd.shutdown()


def post(url, body):
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as e:
        return e.code


def test_the_webhook_server(server):
    base, calls, flaky = server
    with urllib.request.urlopen(base + "/healthz", timeout=5) as response:
        assert response.status == 200
    assert post(base + "/alerts", json.dumps(payload()).encode()) == 200
    assert [type(a) for a in calls] == [Create]
    assert post(base + "/alerts", b"{not json") == 400
    flaky.fail = True
    assert post(base + "/alerts", json.dumps(payload()).encode()) == 502
    assert post(base + "/other", b"{}") == 404
