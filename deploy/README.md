# Deploy

Ops code for running the retrieval API on AWS. The design is in [docs/ops/PLAN.md](../docs/ops/PLAN.md) and the picture is in [docs/ops/architecture.md](../docs/ops/architecture.md). Only the vault sync exists so far.

## Vault sync

`sync/sync_vault.py` copies the vault to the private S3 bucket. It runs on the desktop with Python 3.11 or newer, and it needs only the standard library and this repo's `backend/` folder.

Start with a dry run. It reads the vault, prints counts and the files it would keep home, and uploads nothing:

```
python deploy/sync/sync_vault.py --dry-run
```

The vault location comes from the backend's own resolution: `OBSIDIAN_VAULT_PATH` if it is set, otherwise the OneDrive `Documents/Obsidian Vault` folder. Pass `--vault` to point somewhere else.

A file stays on the desktop in any of these cases:

- The indexer would not read it, because of `EXCLUDE_DIRS` and the file name rules in `backend/indexer.py`.
- It is a cloud-only OneDrive placeholder.
- It is not valid UTF-8 text, or it contains NUL bytes the way UTF-16 files do. The indexer couldn't read it anyway, and a key inside could hide from the patterns.
- `.cloudignore` at the vault root names it.
- A pattern in `sync/secret-patterns.txt` matches its path or any line in it.

`.cloudignore` takes one rule per line. `Journal/` keeps a folder home, `Money/*.md` is a glob from the vault root, and `diary.md` matches that file name in any folder. Matching ignores case, and `#` starts a comment.

The report gives the pattern name and line number for each refused file. It never prints what matched.

A real run needs the bucket from week 1 and the `vault-sync` AWS profile:

```
python deploy/sync/sync_vault.py --bucket BUCKET --dataset backend/eval/dataset.jsonl
```

It mirrors the upload set into `%LOCALAPPDATA%\second-brain-ops\vault-staging` and runs `aws s3 sync --delete`, so a note that becomes refused or ignored also leaves the bucket. It refuses a staging folder that overlaps the vault, because the mirror deletes every file that is not in the upload set.

Tests: `python -m pytest deploy/sync/tests -q`
