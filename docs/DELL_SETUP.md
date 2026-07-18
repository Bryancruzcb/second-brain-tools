# Dell/Windows chat archiver setup

This setup registers a current-user Windows Task Scheduler job named **Second Brain Chat Archiver**. It runs the shared Python collector every day at 11:00 p.m. and writes into a local, OneDrive-synced Obsidian vault. The installer can also add a logon trigger, which is useful when the Dell was asleep or signed out at 11:00 p.m.

## What this can and cannot collect

The collector automatically reads local Gemini/Antigravity, Codex, and Claude Code session files. Consumer ChatGPT Desktop/web, Claude Desktop/web, and Gemini web history remain cloud-side; being signed in through a desktop application or browser does not expose those histories to a local scheduled script. The collector can import downloaded ChatGPT and Claude `conversations.json` exports, but it cannot request those exports from the providers for you. Regular Gemini web exports are not yet supported.

The task does not scrape signed-in browser sessions, store provider passwords, or call provider cloud APIs. Put extracted export files in one of these default locations so subsequent scheduled runs discover them:

```text
%USERPROFILE%\SecondBrainImports\ChatGPT\conversations.json
%USERPROFILE%\SecondBrainImports\Claude\conversations.json
```

The collector also recognizes `%USERPROFILE%\Documents\ChatGPTExport` and `%USERPROFILE%\Documents\ClaudeExport` when the preferred import folders do not exist. Replace the export file when you download a newer copy; daily notes are regenerated idempotently for the configured lookback dates. The scheduled task passes these values to `scripts/chat_archiver.py`:

- the local OneDrive Obsidian vault via `--vault`;
- the local run-status JSON path via `--status-file`;
- a two-day catch-up window via `--lookback-days 2` by default.

## Prerequisites

1. Keep this repository in a stable local directory. The scheduled task stores the collector's absolute path; moving the repository later requires reinstalling the task with `-Force`.
2. Install Python 3.10 or newer for the current user. The installer resolves `py.exe`, `python.exe`, or `python3.exe` to an absolute compatible interpreter path so Task Scheduler does not depend on its reduced `PATH`.
3. Install and sign in to OneDrive. Make the Obsidian vault available locally, open it once in Obsidian, and wait for OneDrive to finish syncing before installation.
4. Use Windows PowerShell 5.1 or PowerShell 7 with the built-in `ScheduledTasks` module.

No provider credentials belong in these scripts or in Task Scheduler arguments.

## Install

Open PowerShell as the same Windows user who runs OneDrive and the desktop chat applications. Administrator access is normally unnecessary for a current-user task.

From the repository root, preview the installation first:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Install-ChatArchiverTask.ps1 `
  -VaultPath "$env:OneDrive\Documents\Obsidian Vault" `
  -AtLogon `
  -WhatIf
```

Then install it:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Install-ChatArchiverTask.ps1 `
  -VaultPath "$env:OneDrive\Documents\Obsidian Vault" `
  -AtLogon
```

`-VaultPath` can be omitted when there is exactly one recognizable Obsidian vault under a registered local OneDrive directory. If more than one candidate exists, the installer stops and asks for an exact path rather than guessing. An explicit vault path may use `$env:OneDriveConsumer`, `$env:OneDriveCommercial`, or a full path.

Useful options:

- `-AtLogon` adds a logon trigger in addition to the daily 23:00 trigger.
- `-WakeToRun` asks Windows to wake the laptop; firmware and Windows power settings can still prevent it.
- `-RunNow` starts a validation run immediately after registration.
- `-DailyTime HH:mm` changes the local daily time.
- `-LookbackDays 1..31` changes the catch-up window; the default of two covers a run missed overnight.
- `-PythonPath 'C:\...\python.exe'` selects a specific Python 3 interpreter.
- `-StatusFile 'C:\...\chat-archiver-status.json'` changes the local status path.
- `-Force` safely replaces an existing task definition after the repository, vault, Python, or schedule changes.

The task uses the current user's interactive token and stores no password. Consequently, the user must be signed in for its OneDrive and local application sources to be available. `StartWhenAvailable` is enabled, so Windows can start a missed daily run after the machine becomes available; `-AtLogon` provides an additional explicit catch-up opportunity.

## Validate

Check the registered schedule and the collector's latest status:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Get-ChatArchiverStatus.ps1
```

For machine-readable output:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Get-ChatArchiverStatus.ps1 -AsJson
```

First, scan without writing any notes:

```powershell
py -3 .\scripts\chat_archiver.py `
  --vault "$env:OneDrive\Documents\Obsidian Vault" `
  --status-file "$env:LOCALAPPDATA\SecondBrain\chat-archiver-status.json" `
  --dry-run
```

Then start the registered task without waiting for 11:00 p.m.:

```powershell
Start-ScheduledTask -TaskName 'Second Brain Chat Archiver'
Start-Sleep -Seconds 5
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\Get-ChatArchiverStatus.ps1
```

The default local files are:

```text
%LOCALAPPDATA%\SecondBrain\chat-archiver-task.json
%LOCALAPPDATA%\SecondBrain\chat-archiver-status.json
```

After a successful run, verify all three signals:

1. `LastTaskResultHex` is `0x00000000` in the status command.
2. The status JSON shows a completed collector run and provider counts/errors.
3. A new or updated note is present under `05 AI Chats` in the selected Obsidian vault and OneDrive reports it as synced.

A provider count of zero can be valid when there were no supported local sessions. It does not prove that cloud-only conversations were scanned.

### Backfill supported local sessions

The scheduled task intentionally scans today and yesterday. To import older supported local sessions already on the Dell, run a one-time backfill for up to 31 days:

```powershell
py -3 .\scripts\chat_archiver.py `
  --vault "$env:OneDrive\Documents\Obsidian Vault" `
  --status-file "$env:LOCALAPPDATA\SecondBrain\chat-archiver-status.json" `
  --lookback-days 31
```

For a specific older date, use `--date YYYY-MM-DD`. Backfill finds local Gemini/Antigravity, Codex, and Claude Code sessions plus dates present in downloaded ChatGPT/Claude exports. It does not retrieve cloud history by itself.

## Troubleshooting

### Compatible Python was not found

Run `py -3 --version`. If it reports Python 3.10 or newer, retry the installer. Otherwise install a compatible Python or pass its full path:

```powershell
.\scripts\windows\Install-ChatArchiverTask.ps1 `
  -PythonPath "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe" `
  -VaultPath "$env:OneDrive\Documents\Obsidian Vault" `
  -Force
```

### No vault or multiple vaults were found

Use the exact local folder with `-VaultPath`. Do not pass an `https://` OneDrive URL. Confirm the folder exists locally and, ideally, contains an `.obsidian` directory. If Files On-Demand left it cloud-only, choose **Always keep on this device** in File Explorer and wait for sync.

### The task did not run at 11:00 p.m.

The Dell may have been asleep, powered off, or signed out. `StartWhenAvailable` handles many missed runs after wake. Reinstall with `-AtLogon` for an additional trigger or `-WakeToRun` if the Dell's power policy permits scheduled wake. Check **Event Viewer → Applications and Services Logs → Microsoft → Windows → TaskScheduler → Operational** for the exact launch result.

### The task ran but no note appeared

Inspect `%LOCALAPPDATA%\SecondBrain\chat-archiver-status.json` and the output from `Get-ChatArchiverStatus.ps1`. Then run the collector interactively to expose path or source errors:

```powershell
py -3 .\scripts\chat_archiver.py `
  --vault "$env:OneDrive\Documents\Obsidian Vault" `
  --status-file "$env:LOCALAPPDATA\SecondBrain\chat-archiver-status.json"
```

If only cloud chats are missing, download a fresh ChatGPT or Claude data export and place its `conversations.json` in the import folder shown above. Gemini web history still needs a future supported export format. The Windows schedule cannot create access that the providers do not expose locally.

### The repository, Python, or vault moved

Rerun the installer with the new paths and `-Force`. The absolute paths are recorded in both Task Scheduler and `%LOCALAPPDATA%\SecondBrain\chat-archiver-task.json`.

## Uninstall

Preview removal:

```powershell
.\scripts\windows\Uninstall-ChatArchiverTask.ps1 -WhatIf
```

Remove only the scheduled task, preserving diagnostic state and all archived notes:

```powershell
.\scripts\windows\Uninstall-ChatArchiverTask.ps1
```

Also delete the installer/status JSON files:

```powershell
.\scripts\windows\Uninstall-ChatArchiverTask.ps1 -RemoveState
```

Uninstall never removes archived notes from the Obsidian vault.
