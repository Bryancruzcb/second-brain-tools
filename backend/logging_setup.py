"""How this process logs: the human format on the desktop, JSON in a pod.

Two rules live here.

A log line never carries the user's question. The app never logs query
text, but uvicorn's access line is the raw request line, so
``GET /api/search?q=...`` would put the question in the pod's stdout and in
anything that ships it. QueryStringFilter cuts it out at the handler, which
covers any future logger that formats a URL the same way.

A record is one line. `kubectl logs` and every shipper downstream split on
newlines, so a plain multi-line traceback arrives as several unrelated
entries; the JSON formatter folds the traceback into one field.
"""
import json
import logging
import sys

import config

PLAIN_FORMAT = "%(levelname)s:%(name)s:%(message)s"

# uvicorn's access logger formats (client, method, full_path, http_version,
# status) and is the only logger in this process that sees a query string.
ACCESS_LOGGERS = ("uvicorn.access",)
ACCESS_RECORD_ARITY = 5
REDACTED = "?<redacted>"


class QueryStringFilter(logging.Filter):
    """Drop everything after the ``?`` in a logged request line.

    Leaves a marker rather than the bare path, so a line that had a query
    string is still recognisable as one — useful when a route starts
    getting called with parameters nobody expected.
    """

    def filter(self, record):
        args = record.args
        if (
            isinstance(args, tuple)
            and len(args) == ACCESS_RECORD_ARITY
            and isinstance(args[2], str)
            and "?" in args[2]
        ):
            path = args[2].partition("?")[0]
            record.args = (args[0], args[1], path + REDACTED, args[3], args[4])
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per record: time, level, logger, message."""

    def format(self, record):
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure(log_format=None):
    """Install this process's single log handler. Safe to call twice.

    Called at import so the startup lines are formatted, and again from the
    lifespan because uvicorn installs its own handlers on the uvicorn.*
    loggers when the server starts. The second call takes those handlers
    away again and lets the records propagate to the root handler here, so
    every line in the pod is formatted the same way and every line passes
    the filter.
    """
    log_format = log_format or config.get_log_format()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter() if log_format == "json" else logging.Formatter(PLAIN_FORMAT)
    )
    handler.addFilter(QueryStringFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)

    for name in ACCESS_LOGGERS:
        access = logging.getLogger(name)
        access.handlers = []
        access.propagate = True
    return handler
