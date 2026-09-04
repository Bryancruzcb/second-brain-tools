"""The nightly orchestrator's process runners, exercised with real subprocesses.

scripts/auto_archive.py is not a package, so it is loaded from its path.
"""
import importlib.util
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_auto_archive():
    path = os.path.join(REPO_ROOT, "scripts", "auto_archive.py")
    spec = importlib.util.spec_from_file_location("auto_archive", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_module_reports_success_and_indents_child_output(capsys):
    auto_archive = _load_auto_archive()
    ok = auto_archive.run_module(sys.executable, "json.tool", args=("--help",), cwd=REPO_ROOT)
    out = capsys.readouterr().out
    assert ok is True
    assert "Success: json.tool" in out
    assert "  usage:" in out  # the child's stdout, indented like every other step


def test_run_module_reports_failure_on_nonzero_exit():
    auto_archive = _load_auto_archive()
    assert auto_archive.run_module(sys.executable, "no_such_module_xyz", cwd=REPO_ROOT) is False


def test_run_script_still_skips_missing_files(capsys):
    auto_archive = _load_auto_archive()
    assert auto_archive.run_script(sys.executable, os.path.join(REPO_ROOT, "nope.py")) is False
