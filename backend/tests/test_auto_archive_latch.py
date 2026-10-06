"""--daily latch: a daytime run must not swallow the 9 PM nightly run."""
import datetime as dt
import importlib.util
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(tmp_path, marker):
    path = os.path.join(REPO_ROOT, "scripts", "auto_archive.py")
    spec = importlib.util.spec_from_file_location("auto_archive_latch", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.MARKER_FILE = str(tmp_path / "marker")
    m.NIGHTLY_HOUR = 21
    if marker is not None:
        (tmp_path / "marker").write_text(marker, encoding="utf-8")
    return m


def T(h, m=0, day=5):
    return dt.datetime(2026, 10, day, h, m)


def test_no_marker_runs(tmp_path):
    assert _load(tmp_path, None).already_ran_today(T(21)) is False


def test_daytime_run_does_not_block_nightly(tmp_path):
    m = _load(tmp_path, "2026-10-05T16:30:21")
    assert m.already_ran_today(T(21, 0)) is False


def test_daytime_run_blocks_second_daytime_logon(tmp_path):
    m = _load(tmp_path, "2026-10-05T16:30:21")
    assert m.already_ran_today(T(18)) is True


def test_nightly_run_blocks_later_logon(tmp_path):
    m = _load(tmp_path, "2026-10-05T21:02:00")
    assert m.already_ran_today(T(23)) is True


def test_yesterday_marker_runs(tmp_path):
    m = _load(tmp_path, "2026-10-04T21:02:00")
    assert m.already_ran_today(T(8)) is False


def test_legacy_date_only_marker(tmp_path):
    m = _load(tmp_path, "2026-10-05")
    assert m.already_ran_today(T(12)) is True
    assert m.already_ran_today(T(21, 5)) is False


def test_marker_written_with_time(tmp_path):
    m = _load(tmp_path, None)
    m.write_success_marker()
    dt.datetime.fromisoformat((tmp_path / "marker").read_text(encoding="utf-8"))
