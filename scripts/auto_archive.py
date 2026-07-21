"""
auto_archive.py — nightly orchestrator for the chat-archive + RAG pipeline.

Runs, in order:
  1. batch_export_claude.py
  2. batch_export_codex.py
  3. batch_export_gemini.py
  4. clean_empty_chats.py
  5. rebuild_chat_indices.py
  6. vault_health_checker.py
  7. backend/scripts/rebuild_rag_index.py (incremental, via the backend venv)
Then backs up the Obsidian vault to a dated zip and prunes old backups.

All paths are resolved relative to this file / sb_common — nothing is
hardcoded to a specific machine's home directory or OneDrive layout.
"""
import os
import sys
import subprocess
import shutil
import datetime

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPTS_DIR)

sys.path.insert(0, SCRIPTS_DIR)
import sb_common  # noqa: E402


def run_script(python_exe, script_path):
    """Run a script with the given interpreter, printing indented output.

    Returns True on success (exit code 0 and the script exists), False otherwise.
    """
    name = os.path.basename(script_path)
    print(f"Running script: {name}...")

    if not os.path.exists(script_path):
        print(f"Script not found, skipping: {script_path}", file=sys.stderr)
        return False

    try:
        res = subprocess.run([python_exe, script_path], capture_output=True, text=True)
        if res.returncode == 0:
            print(f"Success: {name}")
            if res.stdout:
                for line in res.stdout.strip().split('\n'):
                    print(f"  {line}")
            return True
        else:
            print(f"Error executing {name} (Exit Code: {res.returncode}):", file=sys.stderr)
            print(res.stderr, file=sys.stderr)
            return False
    except Exception as e:
        print(f"Failed to execute {name}: {e}", file=sys.stderr)
        return False


def create_vault_backup(vault_dir, backup_dir):
    os.makedirs(backup_dir, exist_ok=True)

    date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    backup_base = os.path.join(backup_dir, f"vault-backup-{date_str}")
    zip_path = backup_base + ".zip"

    print("Creating backup of Obsidian Vault...")
    try:
        shutil.make_archive(backup_base, 'zip', vault_dir)
        print(f"Backup created successfully: {zip_path}")
        return True
    except Exception as e:
        print(f"Failed to create backup: {e}", file=sys.stderr)
        return False


def prune_old_backups(backup_dir, keep_limit=7):
    print(f"Pruning old backups (keeping last {keep_limit})...")
    try:
        backups = []
        for f in os.listdir(backup_dir):
            if f.startswith("vault-backup-") and f.endswith(".zip"):
                fp = os.path.join(backup_dir, f)
                backups.append((fp, os.path.getmtime(fp)))

        # Sort by mtime ascending (oldest first)
        backups.sort(key=lambda x: x[1])

        if len(backups) > keep_limit:
            to_delete = backups[:len(backups) - keep_limit]
            for fp, _ in to_delete:
                try:
                    os.remove(fp)
                    print(f"Deleted old backup: {os.path.basename(fp)}")
                except Exception as e:
                    print(f"Failed to delete old backup {fp}: {e}", file=sys.stderr)
        else:
            print("No old backups needed pruning.")
        return True
    except Exception as e:
        print(f"Error pruning backups: {e}", file=sys.stderr)
        return False


def main():
    failures = 0
    steps_run = 0

    print("=" * 60)
    print(f"=== STARTING SECOND BRAIN AUTO-ARCHIVE & SYNC DAEMON ({datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===")
    print("=" * 60 + "\n")

    # 1. Run all chat export and cleanup scripts in order, in SCRIPTS_DIR.
    scripts_to_run = [
        os.path.join(SCRIPTS_DIR, "batch_export_claude.py"),
        os.path.join(SCRIPTS_DIR, "batch_export_codex.py"),
        os.path.join(SCRIPTS_DIR, "batch_export_gemini.py"),
        os.path.join(SCRIPTS_DIR, "clean_empty_chats.py"),
        os.path.join(SCRIPTS_DIR, "rebuild_chat_indices.py"),
        os.path.join(SCRIPTS_DIR, "vault_health_checker.py"),
    ]

    for script in scripts_to_run:
        steps_run += 1
        if not run_script(sys.executable, script):
            failures += 1

    print("")

    # 2. Rebuild the RAG vector index (incremental by default) using the
    #    backend venv interpreter if it's available, else fall back to the
    #    interpreter running this script.
    venv_python = os.path.join(REPO_ROOT, "backend", "venv", "Scripts", "python.exe")
    if not os.path.exists(venv_python):
        venv_python = sys.executable
    rag_script = os.path.join(REPO_ROOT, "backend", "scripts", "rebuild_rag_index.py")

    steps_run += 1
    if not run_script(venv_python, rag_script):
        failures += 1

    print("")

    # 3. Run Obsidian Vault backup
    vault_dir = sb_common.get_vault_path()
    backup_dir = os.path.join(os.path.expanduser('~'), 'Documents', 'Obsidian Vault Backup')

    steps_run += 1
    if not create_vault_backup(vault_dir, backup_dir):
        failures += 1

    print("")

    # 4. Clean up older backups
    steps_run += 1
    if not prune_old_backups(backup_dir, keep_limit=7):
        failures += 1

    print("\n" + "=" * 60)
    print(f"=== AUTO-ARCHIVE & SYNC DAEMON FINISHED: {steps_run - failures}/{steps_run} steps succeeded"
          f"{f', {failures} FAILED' if failures else ''} ===")
    print("=" * 60)

    if failures:
        sys.exit(1)


if __name__ == '__main__':
    main()
