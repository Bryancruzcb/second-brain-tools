"""Turn Alertmanager webhooks into GitHub issues: one issue per alert and namespace.

Alertmanager posts a group of alerts (grouped by alertname and namespace, see
prometheus.yaml). This opens an issue when the group starts firing, comments
when Alertmanager repeats or updates it, and comments and closes the issue
when it resolves. The open issue on GitHub is the only state, so the bridge
can restart at any time without opening duplicates.

The repository is public, so what reaches GitHub is limited here as well as
in the rules: an allow-list of label keys, the summary annotation with its
whitespace collapsed and cut to a fixed length, and timestamps. Alert rules
only ever quote metric values, and no metric carries note content
(backend/metrics.py).

Shape: the calculations (title, bodies, plan) take the webhook payload as
data and return data; the actions (GitHub calls, the HTTP server) sit at the
edge and only apply what `plan` returns. The server is single-threaded on
purpose: webhooks are handled one at a time, so a retried notification can't
race the original into two issues.

Standard library only, so it runs in the stock python image from a ConfigMap.
With no token (the Parameter Store value doesn't exist yet) it logs what it
would have done and changes nothing.

Environment:
  GITHUB_REPO        owner/name, default Bryancruzcb/second-brain-tools
  GITHUB_TOKEN_FILE  a fine-grained token with Issues read and write
  PORT               default 9095
"""
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer

ALERT_LABEL = "alert"
KEPT_LABELS = ("alertname", "namespace", "severity")
SUMMARY_LIMIT = 300
API = "https://api.github.com"


@dataclass(frozen=True)
class Create:
    title: str
    body: str


@dataclass(frozen=True)
class Comment:
    number: int
    body: str


@dataclass(frozen=True)
class Close:
    number: int


# Calculations: payload in, text and actions out.

def group_key(payload):
    """alertname and namespace from the group labels: the issue's identity."""
    labels = payload.get("groupLabels") or payload.get("commonLabels") or {}
    return str(labels.get("alertname", "unknown")), labels.get("namespace")


def issue_title(payload):
    alertname, namespace = group_key(payload)
    return f"Alert: {alertname} in {namespace}" if namespace else f"Alert: {alertname}"


def clean_summary(alert):
    summary = " ".join(str((alert.get("annotations") or {}).get("summary", "")).split())
    return summary if len(summary) <= SUMMARY_LIMIT else summary[:SUMMARY_LIMIT - 1] + "…"


def alert_lines(payload):
    """One line per alert: its status, kept labels, start time and summary."""
    lines = []
    for alert in payload.get("alerts") or []:
        labels = alert.get("labels") or {}
        kept = ", ".join(f"{k}={labels[k]}" for k in KEPT_LABELS if k in labels)
        lines.append(f"- **{alert.get('status', '?')}** ({kept}) since {alert.get('startsAt', '?')}: "
                     f"{clean_summary(alert)}")
    return lines


def comment_body(payload):
    head = "Resolved." if payload.get("status") == "resolved" else "Still firing."
    return "\n".join([head, "", *alert_lines(payload)])


def issue_body(payload):
    return "\n".join([
        "Opened by the alert bridge (`deploy/monitoring/alert_bridge.py`) from Alertmanager.",
        "It closes this issue when the alert resolves.",
        "",
        *alert_lines(payload),
    ])


def plan(payload, open_issue):
    """The actions for one webhook, given the open issue's number or None."""
    firing = payload.get("status") == "firing"
    if firing and open_issue is None:
        return [Create(issue_title(payload), issue_body(payload))]
    if firing:
        return [Comment(open_issue, comment_body(payload))]
    if open_issue is not None:
        return [Comment(open_issue, comment_body(payload)), Close(open_issue)]
    return []


# Actions: GitHub over HTTPS, and the webhook server.

class GitHub:
    def __init__(self, repo, token):
        self.repo, self.token = repo, token

    def _call(self, method, path, body=None):
        request = urllib.request.Request(
            f"{API}/repos/{self.repo}{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "User-Agent": "second-brain-alert-bridge"})
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            return json.loads(raw) if raw else None

    def open_issue(self, title):
        issues = self._call("GET", f"/issues?labels={ALERT_LABEL}&state=open&per_page=100") or []
        for issue in issues:
            if issue.get("title") == title and "pull_request" not in issue:
                return issue["number"]
        return None

    def apply(self, action):
        match action:
            case Create(title, body):
                self._call("POST", "/issues", {"title": title, "body": body, "labels": [ALERT_LABEL]})
            case Comment(number, body):
                self._call("POST", f"/issues/{number}/comments", {"body": body})
            case Close(number):
                self._call("PATCH", f"/issues/{number}", {"state": "closed", "state_reason": "completed"})
            case _:
                raise TypeError(f"unknown action {action!r}")


def handle(payload, github, log):
    """One webhook, end to end. With no GitHub client it only logs."""
    title = issue_title(payload)
    if github is None:
        log(f"no token, would handle {payload.get('status')} for {title!r}")
        return
    actions = plan(payload, github.open_issue(title))
    for action in actions:
        github.apply(action)
    names = ", ".join(type(a).__name__.lower() for a in actions) or "nothing to do"
    log(f"{payload.get('status')} {title!r}: {names}")


def read_token(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def make_handler(github, log):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.path == "/healthz" else 404)
            self.end_headers()

        def do_POST(self):
            # Read the body before answering anything: closing a socket with
            # unread data resets the connection on some platforms.
            body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
            if self.path != "/alerts":
                self.send_response(404)
                self.end_headers()
                return
            try:
                payload = json.loads(body)
            except ValueError:
                # Retrying a body that doesn't parse can't help.
                self.send_response(400)
                self.end_headers()
                return
            try:
                handle(payload, github, log)
                self.send_response(200)
            except (urllib.error.URLError, OSError) as e:
                # A 5xx makes Alertmanager retry the notification later.
                log(f"failed: {type(e).__name__}")
                self.send_response(502)
            self.end_headers()

        def log_message(self, *args):
            pass

    return Handler


def main():
    repo = os.environ.get("GITHUB_REPO", "Bryancruzcb/second-brain-tools")
    token = read_token(os.environ.get("GITHUB_TOKEN_FILE", "/etc/github/token"))

    def log(message):
        print(message, flush=True)

    github = GitHub(repo, token) if token else None
    log(f"alert bridge for {repo}: {'posting issues' if github else 'no token, logging only'}")
    HTTPServer(("", int(os.environ.get("PORT", "9095"))), make_handler(github, log)).serve_forever()


if __name__ == "__main__":
    sys.exit(main())
