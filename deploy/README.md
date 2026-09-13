# Deploy

Ops code for running the retrieval API on AWS. The design is in [docs/ops/PLAN.md](../docs/ops/PLAN.md) and the picture is in [docs/ops/architecture.md](../docs/ops/architecture.md). The vault sync and the Terraform for the AWS environment exist so far.

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

## Terraform

`terraform/bootstrap/` creates the bucket that holds state, and `terraform/` builds everything else. `ops.py` runs both and prints each command before it runs. It needs Terraform 1.16, the AWS CLI, and credentials for the account, for example from `aws login`.

Copy `terraform/terraform.tfvars.example` to `terraform/terraform.tfvars`, which git ignores, and fill in the account ID and alert email. Then, once per account:

```
python deploy/ops.py bootstrap
python deploy/ops.py init
python deploy/ops.py down
```

`down` applies with the node off and `up` applies with it on, and either is safe to run twice. `plan` previews changes, and `plan --up` previews them with the node on. `tunnel` forwards `localhost:8000` to the API on the node through SSM and needs the Session Manager plugin.

The first apply runs from the desktop, because the GitHub roles don't exist until it finishes. After it, set the repo variables `AWS_ACCOUNT_ID`, `TF_STATE_BUCKET`, and `OPS_STATE` and the secret `ALERT_EMAIL`, so pull requests get plans and main gets applies. AWS also emails a confirmation link for the alert topic, and nothing gets delivered until someone clicks it.

After every `up` or `down`, set `OPS_STATE` to match. Otherwise the next merge that touches `deploy/terraform/` applies the old node setting.

If `terraform init` fails with "Failed to query available provider packages" and a connection reset, the network's IPv6 route to the Terraform registry is probably broken while IPv4 works. Copy the provider binaries from a working `.terraform/providers` folder into a local folder and point init at it:

```
python deploy/ops.py init "-plugin-dir=C:\path\to\terraform-providers"
```

`ops.py bootstrap` passes extra arguments only to apply, so on such a network run its two steps by hand: `terraform -chdir=deploy/terraform/bootstrap init -plugin-dir=...`, then `terraform -chdir=deploy/terraform/bootstrap apply -var=account_id=...`.

Tests: `python -m pytest deploy/tests -q`
