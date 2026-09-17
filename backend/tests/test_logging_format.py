"""LOG_FORMAT=json, and no question in a log line."""
import json
import logging

import pytest

import config
import logging_setup


@pytest.fixture(autouse=True)
def restore_root_logging():
    """Give each test the root logger back; configure() replaces handlers."""
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    access = logging.getLogger("uvicorn.access")
    saved_access, propagate = access.handlers[:], access.propagate
    yield
    root.handlers, root.level = saved, level
    access.handlers, access.propagate = saved_access, propagate


def access_record(full_path):
    """A record shaped exactly like uvicorn's access line."""
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1234", "GET", full_path, "1.1", 200),
        None,
    )
    return record


def test_query_string_is_cut_out_of_the_access_line():
    record = access_record("/api/search?q=my+therapist+said+what")
    assert logging_setup.QueryStringFilter().filter(record) is True
    assert "therapist" not in record.getMessage()
    assert "/api/search?<redacted>" in record.getMessage()


def test_a_plain_path_survives_untouched():
    record = access_record("/api/ready")
    logging_setup.QueryStringFilter().filter(record)
    assert '"GET /api/ready HTTP/1.1" 200' in record.getMessage()


def test_json_format_is_one_parseable_line(capsys):
    logging_setup.configure("json")
    logging.getLogger("second-brain-backend").info("index rebuilt: %d chunks", 12)
    line = capsys.readouterr().out.strip()
    assert "\n" not in line
    entry = json.loads(line)
    assert entry["message"] == "index rebuilt: 12 chunks"
    assert entry["level"] == "INFO"
    assert entry["logger"] == "second-brain-backend"
    assert entry["time"]


def test_a_traceback_stays_one_entry(capsys):
    logging_setup.configure("json")
    try:
        raise RuntimeError("store is mid-swap")
    except RuntimeError:
        logging.getLogger("second-brain-backend").exception("ingestion failed")
    line = capsys.readouterr().out.strip()
    assert "\n" not in line          # kubectl logs splits on newlines
    entry = json.loads(line)
    assert entry["message"] == "ingestion failed"
    assert "RuntimeError: store is mid-swap" in entry["exception"]


def test_access_lines_go_through_the_json_handler(capsys):
    """uvicorn's own handler is removed, so its records reach ours filtered."""
    logging_setup.configure("json")
    logging.getLogger("uvicorn.access").handle(access_record("/api/search?q=private"))
    entry = json.loads(capsys.readouterr().out.strip())
    assert "private" not in entry["message"]
    assert entry["logger"] == "uvicorn.access"


def test_plain_format_is_the_default(capsys, monkeypatch):
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    logging_setup.configure()
    logging.getLogger("second-brain-backend").info("hello")
    assert capsys.readouterr().out.strip() == "INFO:second-brain-backend:hello"


def test_configure_installs_exactly_one_handler():
    logging_setup.configure("json")
    logging_setup.configure("json")
    assert len(logging.getLogger().handlers) == 1
    assert logging.getLogger("uvicorn.access").handlers == []


@pytest.mark.parametrize(
    "raw,expected",
    [("json", "json"), ("JSON", "json"), (" json ", "json"),
     ("plain", "plain"), ("", "plain"), ("text", "plain")],
)
def test_format_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("LOG_FORMAT", raw)
    assert config.get_log_format() == expected
