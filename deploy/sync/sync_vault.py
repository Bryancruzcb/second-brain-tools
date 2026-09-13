"""Copy the vault to the private S3 bucket, minus anything that looks like a credential.

Runs on the desktop, where the vault lives. The file list comes from the
indexer's own scanner in backend/indexer.py, so the bucket holds exactly what
the cloud indexer reads and the two can't drift. From that list it drops
cloud-only OneDrive placeholders, anything .cloudignore at the vault root
names, and every file a pattern in secret-patterns.txt matches. The rest goes
into a local staging mirror, and `aws s3 sync --delete` makes the bucket match
it, so a note that becomes refused or ignored also leaves the bucket on the
next run.

The report names refused files with the pattern and line that matched. It
never prints file contents or the matched text.

Usage (from the repo root):
    python deploy/sync/sync_vault.py --dry-run
    python deploy/sync/sync_vault.py --bucket BUCKET [--dataset backend/eval/dataset.jsonl]
"""
import argparse
import fnmatch
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "backend"))

import config
import indexer

DEFAULT_PATTERNS = os.path.join(HERE, "secret-patterns.txt")
CLOUDIGNORE = ".cloudignore"
DATASET_KEY = "eval/dataset.jsonl"
AWS_CLI_WINDOWS = r"C:\Program Files\Amazon\AWSCLIV2\aws.exe"
REASONS_SHOWN = 5
UNREADABLE = "unreadable, so it could not be scanned"


@dataclass(frozen=True)
class Pattern:
    kind: str  # "content" runs on each line of a file, "path" on its path from the vault root
    name: str
    regex: re.Pattern


@dataclass
class SyncPlan:
    upload: list = field(default_factory=list)        # (rel_path, full_path)
    placeholders: list = field(default_factory=list)  # cloud-only OneDrive stubs, never read
    ignored: list = field(default_factory=list)       # named by .cloudignore
    refused: dict = field(default_factory=dict)       # rel_path -> reasons


def default_staging():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "second-brain-ops", "vault-staging")


def load_patterns(path):
    """Read `kind name regex` lines; blank lines and # comments are skipped."""
    patterns = []
    with open(path, "r", encoding="utf-8-sig") as f:
        for number, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 2)
            if len(parts) != 3 or parts[0] not in ("content", "path"):
                raise ValueError(f"{path}:{number}: expected 'content|path name regex'")
            try:
                regex = re.compile(parts[2])
            except re.error as e:
                raise ValueError(f"{path}:{number}: bad regex for {parts[1]}: {e}") from e
            patterns.append(Pattern(parts[0], parts[1], regex))
    return patterns


def load_cloudignore(vault):
    """Rules from <vault>/.cloudignore, lowercased, with forward slashes."""
    path = os.path.join(vault, CLOUDIGNORE)
    if not os.path.isfile(path):
        return []
    # utf-8-sig: Windows PowerShell 5.1 saves a byte order mark, which would hide the first rule.
    with open(path, "r", encoding="utf-8-sig") as f:
        rules = [line.strip() for line in f]
    return [rule.replace("\\", "/").lower() for rule in rules if rule and not rule.startswith("#")]


def is_ignored(rel_path, rules):
    """True when a .cloudignore rule covers this vault-relative path.

    `Folder/` keeps a folder home, a rule containing a slash is a glob over the
    path from the vault root, and a rule without one also matches the file name
    in any folder. Case is ignored, as on the Windows file system.
    """
    rel = rel_path.lower()
    name = rel.rsplit("/", 1)[-1]
    for rule in rules:
        rule = rule.lstrip("/")
        if rule.endswith("/"):
            if rel.startswith(rule):
                return True
        elif fnmatch.fnmatchcase(rel, rule) or ("/" not in rule and fnmatch.fnmatchcase(name, rule)):
            return True
    return False


def read_text(path):
    """A file's text for scanning, or None when it can't be scanned.

    The indexer reads notes as strict UTF-8, so a file that fails to decode would
    never be indexed and has no reason to leave the desktop. NUL bytes keep a
    file home too: UTF-16 text is full of them, and they split every key apart so
    no pattern can match it.
    """
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def scan_file(rel_path, full_path, patterns):
    """Reasons to keep a file home, like 'anthropic-key (line 12)'. Empty means clean."""
    reasons = [f"{p.name} (path)" for p in patterns if p.kind == "path" and p.regex.search(rel_path)]
    text = read_text(full_path)
    if text is None:
        return reasons + [UNREADABLE]
    content = [p for p in patterns if p.kind == "content"]
    for number, line in enumerate(text.split("\n"), 1):
        reasons.extend(f"{p.name} (line {number})" for p in content if p.regex.search(line))
    return reasons


def build_plan(vault, patterns, rules):
    """Sort every file the indexer reads into upload, placeholder, ignored, or refused."""
    plan = SyncPlan()
    for rel_path, full_path in indexer._scan_vault(vault):
        if indexer.is_dataless_file(full_path):
            plan.placeholders.append(rel_path)
        elif is_ignored(rel_path, rules):
            plan.ignored.append(rel_path)
        else:
            reasons = scan_file(rel_path, full_path, patterns)
            if reasons:
                plan.refused[rel_path] = reasons
            else:
                plan.upload.append((rel_path, full_path))
    return plan


def check_staging(staging, vault):
    """Stop when the staging folder and the vault overlap; the mirror deletes files in staging."""
    staging_real = os.path.normcase(os.path.realpath(staging))
    vault_real = os.path.normcase(os.path.realpath(vault))
    try:
        shared = os.path.commonpath([staging_real, vault_real])
    except ValueError:  # different drives on Windows
        return
    if shared in (staging_real, vault_real):
        raise SystemExit(f"Staging folder {staging} overlaps the vault {vault}. Pick a folder outside it.")


def mirror(upload, staging):
    """Make the staging folder hold exactly the upload set. Returns (copied, removed)."""
    wanted = dict(upload)
    os.makedirs(staging, exist_ok=True)
    removed = 0
    for root, dirs, files in os.walk(staging, topdown=False):
        for name in files:
            path = os.path.join(root, name)
            if os.path.relpath(path, staging).replace("\\", "/") not in wanted:
                os.remove(path)
                removed += 1
        for name in dirs:
            path = os.path.join(root, name)
            if not os.listdir(path):
                os.rmdir(path)
    copied = 0
    for rel_path, source in wanted.items():
        target = os.path.join(staging, *rel_path.split("/"))
        if os.path.isfile(target):
            src, dst = os.stat(source), os.stat(target)
            if src.st_size == dst.st_size and abs(src.st_mtime - dst.st_mtime) < 1:
                continue
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)
        copied += 1
    return copied, removed


def find_aws():
    return shutil.which("aws") or (AWS_CLI_WINDOWS if os.path.isfile(AWS_CLI_WINDOWS) else None)


def sync_command(aws, staging, bucket, prefix, profile):
    return [aws, "s3", "sync", staging, f"s3://{bucket}/{prefix.strip('/')}/", "--delete",
            "--only-show-errors", "--no-progress", "--profile", profile]


def dataset_command(aws, dataset, bucket, profile):
    return [aws, "s3", "cp", dataset, f"s3://{bucket}/{DATASET_KEY}",
            "--only-show-errors", "--no-progress", "--profile", profile]


def print_report(plan, vault):
    total = len(plan.upload) + len(plan.placeholders) + len(plan.ignored) + len(plan.refused)
    print(f"Vault: {vault}")
    print(f"Files the indexer reads: {total}")
    print(f"  cloud-only placeholders, skipped: {len(plan.placeholders)}")
    print(f"  kept home by .cloudignore: {len(plan.ignored)}")
    print(f"  refused by the secret scan: {len(plan.refused)}")
    print(f"  to upload: {len(plan.upload)}")
    if plan.refused:
        print("\nRefused, staying on this PC:")
        for rel_path in sorted(plan.refused):
            reasons = plan.refused[rel_path]
            extra = f", and {len(reasons) - REASONS_SHOWN} more" if len(reasons) > REASONS_SHOWN else ""
            print(f"  {rel_path}: {', '.join(reasons[:REASONS_SHOWN])}{extra}")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="Scan the vault and sync it to the private S3 bucket.")
    parser.add_argument("--dry-run", action="store_true", help="scan and report; copy and upload nothing")
    parser.add_argument("--bucket", help="vault bucket name, required unless --dry-run")
    parser.add_argument("--prefix", default="vault", help="key prefix in the bucket (default: vault)")
    parser.add_argument("--profile", default="vault-sync", help="AWS CLI profile with the uploader key")
    parser.add_argument("--vault", help="vault folder (default: the backend's own vault resolution)")
    parser.add_argument("--staging", default=default_staging(), help="local mirror that gets synced")
    parser.add_argument("--patterns", default=DEFAULT_PATTERNS, help="secret pattern file")
    parser.add_argument("--dataset", help="private eval set, uploaded as eval/dataset.jsonl")
    args = parser.parse_args(argv)
    if not args.dry_run and not args.bucket:
        parser.error("--bucket is required unless --dry-run is set")
    return args


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")  # a title the console can't encode must not crash the run
    except (AttributeError, ValueError):
        pass
    args = parse_args(argv)
    vault = os.path.abspath(args.vault or config.get_vault_path())
    if not os.path.isdir(vault):
        print(f"No vault at {vault}. Set OBSIDIAN_VAULT_PATH or pass --vault.")
        return 1
    patterns = load_patterns(args.patterns)

    # Checked first, so a refused eval set stops the run before anything is copied.
    if args.dataset:
        if not os.path.isfile(args.dataset):
            print(f"No eval set at {args.dataset}.")
            return 1
        reasons = scan_file(DATASET_KEY, args.dataset, patterns)
        if reasons:
            print(f"Refusing to upload the eval set: {', '.join(reasons[:REASONS_SHOWN])}")
            return 1

    plan = build_plan(vault, patterns, load_cloudignore(vault))
    print_report(plan, vault)
    if args.dry_run:
        print("\nDry run: nothing was copied or uploaded.")
        return 0

    aws = find_aws()
    if aws is None:
        print("AWS CLI not found. Install it or put aws on PATH.")
        return 1
    check_staging(args.staging, vault)
    copied, removed = mirror(plan.upload, args.staging)
    print(f"\nStaging mirror: {copied} copied, {removed} removed, in {args.staging}")
    commands = [sync_command(aws, args.staging, args.bucket, args.prefix, args.profile)]
    if args.dataset:
        commands.append(dataset_command(aws, args.dataset, args.bucket, args.profile))
    for command in commands:
        result = subprocess.run(command)
        if result.returncode != 0:
            print(f"aws {command[1]} {command[2]} failed with exit code {result.returncode}")
            return result.returncode
    print(f"Synced {len(plan.upload)} files to s3://{args.bucket}/{args.prefix.strip('/')}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
