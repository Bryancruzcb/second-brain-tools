# Windows autostart

Starts the Night Atlas backend (`uvicorn main:app` on `127.0.0.1:8000`) and
frontend (`bun run dev` on `:3000`) when you log into Windows.

| File | What it does |
|---|---|
| `start-night-atlas.ps1` | The launcher. For each service: if the port already answers, log it and leave it alone; otherwise start it hidden (`backend\venv\Scripts\python.exe -m uvicorn ...` from `backend\`, `bun run dev` from the frontend dir), wait for `GET /api/health` / the port, and log. Never stops or restarts anything, never installs dependencies, never touches Task Scheduler. A named mutex keeps two launchers from racing. `-DryRun` starts nothing. |
| `start-night-atlas-hidden.vbs` | Runs the launcher with no console window (same pattern as `scripts/run_hidden.vbs`). |
| `install-autostart.ps1` | Adds one logon entry named `NightAtlas-Autostart`. Default `-Method StartupFolder`: a shortcut in your Startup folder (no admin, nothing in Task Scheduler changes). `-Method Task`: a Task Scheduler task with that one name. Idempotent; refuses to overwrite a same-named entry it didn't create; starts nothing. `-DryRun` / `-WhatIf` change nothing. |
| `uninstall-autostart.ps1` | Removes only that shortcut and/or task (only if it carries this project's marker). Does not stop running services. |

Logs: `%LOCALAPPDATA%\NightAtlas\logs\autostart.log`, plus per-run
`backend-<stamp>.out.log` / `.err.log` and `frontend-<stamp>.*.log` (newest 20 kept).

## Install

Preview first (changes nothing):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install-autostart.ps1 -DryRun
```

Then install. `-FrontendDir` is only needed when the frontend runs from a
different checkout or worktree than the backend:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install-autostart.ps1 `
    -RepoRoot C:\path\to\second-brain-tools -FrontendDir C:\path\to\worktree\frontend
```

The entry points at the scripts in the checkout you install from, so keep that
checkout on a branch that has `scripts\windows\`. Prerequisites the launcher
expects (it will not create them): `backend\venv` with the requirements
installed, `backend\.env`, and `node_modules` in the frontend dir.

Test the launcher by hand without starting anything:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\start-night-atlas.ps1 -DryRun
```

## Uninstall

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\uninstall-autostart.ps1
```

## Weekly Repair digest

`run-repair-digest.ps1` wraps `scripts/repair_digest.py` for a scheduled task:
if the backend answers `GET /api/health` it writes
`%USERPROFILE%\NightAtlas\repair-digest-<yyyy-MM-dd>.md` and
`repair-digest-latest.json` (also used as `--previous`, so each report diffs
against the last); if not, it logs and exits 0 without starting anything.
Log: `%LOCALAPPDATA%\NightAtlas\logs\repair-digest.log`. The task on the
owner's PC (`NightAtlas-RepairDigest`, Sundays 9:17, only when logged on, start
when available) runs:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\path\to\second-brain-tools\scripts\windows\run-repair-digest.ps1
```

## Tests

`scripts/windows/tests` (Pester 5): unit tests mock every side effect and run
on any pwsh; `Autostart.E2E.Tests.ps1` starts a real tiny backend and
registers a real task, so it only runs with `NIGHTATLAS_E2E=1` on Windows (the
`windows-autostart` CI job).

```powershell
Invoke-Pester scripts/windows/tests
```
