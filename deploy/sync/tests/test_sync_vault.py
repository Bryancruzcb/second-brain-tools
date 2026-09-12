"""What leaves the desktop is decided in sync_vault.py, so these pin the
decision: the file list is the indexer's own, every secret pattern refuses a
fake secret, code and placeholders stay uploadable, the report never echoes a
secret, and the staging mirror can never delete from the vault.
"""
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sync_vault  # puts backend/ on sys.path
import indexer

# Assembled from pieces so no secret-shaped string sits in the repo, where
# GitHub push protection, or this very scan, would flag it.
FAKE_SECRETS = {
    "anthropic-key": "sk-" + "ant-api03-" + "Zx9" * 12,
    "openai-key": "sk-" + "proj-" + "Q7w" * 14,
    "aws-access-key-id": "AK" + "IA" + "Q7W2E4R6T8Y1U3I5",
    "aws-secret-access-key": "aws_secret" + "_access_key = " + "Ab1c" * 10,
    "github-token": "gh" + "p_" + "a1B2" * 9,
    "slack-token": "xo" + "xb-" + "1234567890-abcdefghij",
    "google-api-key": "AI" + "za" + "Sy" + "A1b2C3d4" * 4 + "e",
    "google-oauth-secret": "GOC" + "SPX-" + "a1B2c3D4e5F6g7H8i9J0",
    "huggingface-token": "hf" + "_" + "a1B2c3" * 6,
    "groq-key": "gs" + "k_" + "a1B2c3D4" * 6,
    "xai-key": "xa" + "i-" + "a1B2c3D4" * 6,
    "stripe-live-key": "sk" + "_live_" + "a1B2c3D4" * 3,
    "npm-token": "np" + "m_" + "a1B2c3" * 6,
    "discord-webhook": "https://discord.com/api/" + "webhooks/123456789012345678/" + "aB3_" * 17,
    "jwt": "ey" + "JhbGciOiJIUzI1NiJ9." + "ey" + "JzdWIiOiIxMjM0NTY3ODkwIn0." + "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c",
    "private-key-block": "-----BEGIN " + "OPENSSH PRIVATE KEY-----",
    "bearer-header": "Authorization: " + "Bearer " + "a1B2c3D4e5F6g7H8i9J0k1L2",
    "credential-assignment": "pass" + "word = " + "Tr0ub4dor-horse",
}

# Lines chat transcripts are full of that must not keep a note home.
CLEAN_LINES = [
    'client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])',
    "api_key = settings.ANTHROPIC_API_KEY",
    "API_KEY=${API_KEY}",
    "password: <your-password>",
    "export OPENAI_API_KEY=your-key-here",
    "secret_key = process.env.SECRET_KEY",
    '"password": "hunter"',
    "Authorization: Bearer $TOKEN",
    "Use a password manager and never reuse a password.",
    "An AWS access key ID starts with AKIA, then sixteen more characters.",
    "-----BEGIN CERTIFICATE-----",
    "sk-learn is the usual shorthand for scikit-learn",
]


def _write(root, rel_path, text="plain note\n"):
    path = root.joinpath(*rel_path.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _no_subprocess(*args, **kwargs):
    raise AssertionError("this run must not call the AWS CLI")


@pytest.fixture
def patterns():
    return sync_vault.load_patterns(sync_vault.DEFAULT_PATTERNS)


def test_file_list_is_the_indexers(tmp_path, patterns):
    vault = tmp_path / "vault"
    for rel_path in ["Note.md", "05 AI Chats/Claude/chat.md", "Templates/daily.md",
                     ".obsidian/workspace.md", "99 Archive/old.md", "Projects Index.md",
                     "Vault Health Report.md", "diagram.png"]:
        _write(vault, rel_path)
    plan = sync_vault.build_plan(str(vault), patterns, [])
    from_indexer = sorted(rel for rel, _ in indexer._scan_vault(str(vault)))
    assert sorted(rel for rel, _ in plan.upload) == from_indexer == ["05 AI Chats/Claude/chat.md", "Note.md"]


def test_every_content_pattern_has_a_fake_secret(patterns):
    assert {p.name for p in patterns if p.kind == "content"} == set(FAKE_SECRETS)


@pytest.mark.parametrize("name", sorted(FAKE_SECRETS))
def test_each_pattern_refuses_its_fake_secret(tmp_path, patterns, name):
    note = _write(tmp_path, "note.md", f"first line\nsee {FAKE_SECRETS[name]} here\n")
    assert f"{name} (line 2)" in sync_vault.scan_file("note.md", str(note), patterns)


@pytest.mark.parametrize("line", CLEAN_LINES)
def test_code_and_placeholders_stay_uploadable(tmp_path, patterns, line):
    note = _write(tmp_path, "note.md", line + "\n")
    assert sync_vault.scan_file("note.md", str(note), patterns) == []


def test_credential_file_names_are_refused(tmp_path, patterns):
    keys = _write(tmp_path, "API Keys.md")
    assert sync_vault.scan_file("API Keys.md", str(keys), patterns) == ["credentials-filename (path)"]
    shortcuts = _write(tmp_path, "Keyboard shortcuts.md")
    assert sync_vault.scan_file("Keyboard shortcuts.md", str(shortcuts), patterns) == []


def test_secret_in_a_non_utf8_file_is_still_caught(tmp_path, patterns):
    note = tmp_path / "note.md"
    note.write_bytes(b"\xff\xfe broken bytes " + FAKE_SECRETS["anthropic-key"].encode())
    assert "anthropic-key (line 1)" in sync_vault.scan_file("note.md", str(note), patterns)


def test_a_file_that_cannot_be_read_is_refused(tmp_path, patterns):
    not_a_file = tmp_path / "note.md"
    not_a_file.mkdir()
    assert sync_vault.scan_file("note.md", str(not_a_file), patterns) == [sync_vault.UNREADABLE]


def test_cloud_placeholders_are_skipped_without_being_read(tmp_path, patterns, monkeypatch):
    vault = tmp_path / "vault"
    _write(vault, "local.md")
    _write(vault, "online-only.md")
    monkeypatch.setattr(indexer, "is_dataless_file", lambda path: path.endswith("online-only.md"))
    read = []
    real_read = sync_vault.read_text
    monkeypatch.setattr(sync_vault, "read_text", lambda path: read.append(path) or real_read(path))
    plan = sync_vault.build_plan(str(vault), patterns, [])
    assert plan.placeholders == ["online-only.md"]
    assert [rel for rel, _ in plan.upload] == ["local.md"]
    assert not any(path.endswith("online-only.md") for path in read)


def test_cloudignore_rules(tmp_path, patterns):
    vault = tmp_path / "vault"
    for rel_path in ["Journal/2026-09-01.md", "Money/budget.md", "Notes/diary.md",
                     "Deep/Nested/diary.md", "Notes/kept.md"]:
        _write(vault, rel_path)
    (vault / ".cloudignore").write_text("# kept home\njournal/\nMoney/*.md\ndiary.md\n", encoding="utf-8")
    plan = sync_vault.build_plan(str(vault), patterns, sync_vault.load_cloudignore(str(vault)))
    assert sorted(plan.ignored) == ["Deep/Nested/diary.md", "Journal/2026-09-01.md",
                                    "Money/budget.md", "Notes/diary.md"]
    assert [rel for rel, _ in plan.upload] == ["Notes/kept.md"]


def test_cloudignore_saved_with_a_byte_order_mark_still_works(tmp_path, patterns):
    vault = tmp_path / "vault"
    _write(vault, "Journal/today.md")
    _write(vault, "kept.md")
    (vault / ".cloudignore").write_bytes("journal/\n".encode("utf-8-sig"))
    plan = sync_vault.build_plan(str(vault), patterns, sync_vault.load_cloudignore(str(vault)))
    assert plan.ignored == ["Journal/today.md"]


def test_dry_run_names_refused_files_but_never_the_secret(tmp_path, capsys, monkeypatch):
    vault = tmp_path / "vault"
    _write(vault, "clean.md")
    _write(vault, "05 AI Chats/leaky chat.md", "\n".join(f"{n}: {v}" for n, v in FAKE_SECRETS.items()))
    staging = tmp_path / "staging"
    monkeypatch.setattr(sync_vault.subprocess, "run", _no_subprocess)
    assert sync_vault.main(["--dry-run", "--vault", str(vault), "--staging", str(staging)]) == 0
    out = capsys.readouterr().out
    assert "05 AI Chats/leaky chat.md" in out
    assert "to upload: 1" in out
    for value in FAKE_SECRETS.values():
        assert value not in out
    assert not staging.exists()


def test_real_run_mirrors_then_syncs_with_delete(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    _write(vault, "a.md")
    _write(vault, "b/c.md")
    staging = tmp_path / "staging"
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text('{"question": "q", "expected_sources": ["a.md"]}\n', encoding="utf-8")
    calls = []
    monkeypatch.setattr(sync_vault, "find_aws", lambda: "aws")
    monkeypatch.setattr(sync_vault.subprocess, "run",
                        lambda command: calls.append(command) or subprocess.CompletedProcess(command, 0))
    assert sync_vault.main(["--bucket", "vault-bucket", "--vault", str(vault), "--staging", str(staging),
                            "--dataset", str(dataset)]) == 0
    assert calls == [
        ["aws", "s3", "sync", str(staging), "s3://vault-bucket/vault/", "--delete",
         "--only-show-errors", "--no-progress", "--profile", "vault-sync"],
        ["aws", "s3", "cp", str(dataset), "s3://vault-bucket/eval/dataset.jsonl",
         "--only-show-errors", "--no-progress", "--profile", "vault-sync"],
    ]
    assert sorted(p.relative_to(staging).as_posix() for p in staging.rglob("*") if p.is_file()) == ["a.md", "b/c.md"]


def test_eval_set_with_a_secret_stops_the_run_before_copying(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    _write(vault, "a.md")
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text('{"question": "' + FAKE_SECRETS["github-token"] + '"}\n', encoding="utf-8")
    staging = tmp_path / "staging"
    monkeypatch.setattr(sync_vault, "find_aws", lambda: "aws")
    monkeypatch.setattr(sync_vault.subprocess, "run", _no_subprocess)
    assert sync_vault.main(["--bucket", "b", "--vault", str(vault), "--staging", str(staging),
                            "--dataset", str(dataset)]) == 1
    assert not staging.exists()


def test_mirror_converges_and_removes_what_left_the_upload_set(tmp_path):
    vault = tmp_path / "vault"
    a = _write(vault, "a.md")
    c = _write(vault, "b/c.md")
    staging = tmp_path / "staging"
    upload = [("a.md", str(a)), ("b/c.md", str(c))]
    assert sync_vault.mirror(upload, str(staging)) == (2, 0)
    assert sync_vault.mirror(upload, str(staging)) == (0, 0)
    assert (staging / "a.md").stat().st_mtime == pytest.approx(a.stat().st_mtime, abs=1)
    assert sync_vault.mirror(upload[:1], str(staging)) == (0, 1)
    assert not (staging / "b").exists()


@pytest.mark.parametrize("inside", [".", "sub/staging"])
def test_staging_in_or_as_the_vault_is_refused(tmp_path, inside):
    vault = tmp_path / "vault"
    vault.mkdir()
    with pytest.raises(SystemExit):
        sync_vault.check_staging(str(vault / inside), str(vault))


def test_vault_inside_staging_is_refused(tmp_path):
    vault = tmp_path / "staging" / "vault"
    vault.mkdir(parents=True)
    with pytest.raises(SystemExit):
        sync_vault.check_staging(str(tmp_path / "staging"), str(vault))


def test_run_with_staging_inside_the_vault_deletes_nothing(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    note = _write(vault, "keep.md")
    other = _write(vault, "sub/other.txt")  # outside the upload set, so a mirror here would delete it
    monkeypatch.setattr(sync_vault, "find_aws", lambda: "aws")
    monkeypatch.setattr(sync_vault.subprocess, "run", _no_subprocess)
    with pytest.raises(SystemExit):
        sync_vault.main(["--bucket", "b", "--vault", str(vault), "--staging", str(vault / "sub")])
    assert note.exists() and other.exists()


def test_bucket_is_required_outside_dry_run(tmp_path):
    with pytest.raises(SystemExit):
        sync_vault.main(["--vault", str(tmp_path)])


def test_malformed_pattern_line_names_the_line(tmp_path):
    bad = tmp_path / "patterns.txt"
    bad.write_text("# fine\ncontent only-two-columns\n", encoding="utf-8")
    with pytest.raises(ValueError, match="patterns.txt:2"):
        sync_vault.load_patterns(str(bad))
