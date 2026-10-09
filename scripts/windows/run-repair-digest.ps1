<#
.SYNOPSIS
    Weekly Night Atlas Repair digest (read-only), for a scheduled task.

.DESCRIPTION
    Checks that the backend answers GET /api/health; if it does not, logs that
    and exits 0 without starting anything. Otherwise runs
    scripts\repair_digest.py from this checkout (API only, never the cache
    fallback) with the backend venv's Python and writes
        <OutDir>\repair-digest-<yyyy-MM-dd>.md
        <OutDir>\repair-digest-latest.json   (also passed as --previous)
    so each week's report diffs against the last one. The date expands when
    the script runs. Log: %LOCALAPPDATA%\NightAtlas\logs\repair-digest.log

    Read-only: it never calls a scan or write route and never writes to the
    vault or the index; repair_digest.py itself refuses output paths inside
    OBSIDIAN_VAULT_PATH.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File scripts\windows\run-repair-digest.ps1
#>
[CmdletBinding()]
param(
    # Defaults to the checkout this script lives in (resolved below: Windows
    # PowerShell 5.1 leaves $PSScriptRoot empty in param defaults under -File).
    [string]$RepoRoot = '',
    [string]$ApiUrl = 'http://127.0.0.1:8000',
    [string]$OutDir = '',
    [string]$LogDir = ''
)

Set-StrictMode -Version 2.0

function Write-RepairDigestLog {
    param([string]$Message)
    $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    if ($script:RepairDigestLog) {
        try { Add-Content -LiteralPath $script:RepairDigestLog -Value $line -Encoding UTF8 } catch { }
    }
    Write-Host $line
}

function Test-RepairDigestBackend {
    param([string]$ApiUrl)
    try {
        $r = Invoke-WebRequest -Uri "$ApiUrl/api/health" -UseBasicParsing -TimeoutSec 15
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Invoke-RepairDigestPython {
    # Runs repair_digest.py; returns @{ Code; Output }. Separate so tests can mock it.
    param([string]$Python, [string[]]$Arguments)
    # Windows PowerShell turns a native command's stderr into error records;
    # under 'Stop' the first stderr line would abort the wrapper.
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $Python @Arguments 2>&1
        return @{ Code = $LASTEXITCODE; Output = @($out | ForEach-Object { "$_" }) }
    } finally {
        $ErrorActionPreference = $old
    }
}

function Invoke-RepairDigest {
    param([string]$RepoRoot, [string]$ApiUrl, [string]$OutDir, [string]$LogDir, [datetime]$Now = (Get-Date))
    if (-not $LogDir) { $LogDir = Join-Path (Join-Path $env:LOCALAPPDATA 'NightAtlas') 'logs' }
    if (-not $OutDir) { $OutDir = Join-Path $env:USERPROFILE 'NightAtlas' }
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $script:RepairDigestLog = Join-Path $LogDir 'repair-digest.log'
    try {
        if (-not (Test-RepairDigestBackend -ApiUrl $ApiUrl)) {
            Write-RepairDigestLog "backend not reachable at $ApiUrl; skipping this week's digest. Nothing was started."
            return 0
        }
        $python = Join-Path $RepoRoot 'backend\venv\Scripts\python.exe'
        $digest = Join-Path $RepoRoot 'scripts\repair_digest.py'
        foreach ($p in @($python, $digest)) {
            if (-not (Test-Path -LiteralPath $p)) { Write-RepairDigestLog "missing $p; skipping."; return 1 }
        }
        New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
        $md = Join-Path $OutDir ('repair-digest-{0}.md' -f $Now.ToString('yyyy-MM-dd'))
        $json = Join-Path $OutDir 'repair-digest-latest.json'
        $argv = @($digest, '--source', 'api', '--url', $ApiUrl, '--out', $md, '--json-out', $json)
        # The first run has no previous week to diff against.
        if (Test-Path -LiteralPath $json) { $argv += @('--previous', $json) }
        Write-RepairDigestLog "running digest -> $md"
        $r = Invoke-RepairDigestPython -Python $python -Arguments $argv
        foreach ($line in $r.Output) { if ($line.Trim()) { Write-RepairDigestLog "  $line" } }
        if ($r.Code -eq 0) { Write-RepairDigestLog "digest written: $md (summary $json)" }
        else { Write-RepairDigestLog "repair_digest.py exited $($r.Code)" }
        return $r.Code
    } catch {
        Write-RepairDigestLog "wrapper error: $($_.Exception.Message)"
        return 1
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    if (-not $RepoRoot) { $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
    exit (Invoke-RepairDigest -RepoRoot $RepoRoot -ApiUrl $ApiUrl -OutDir $OutDir -LogDir $LogDir)
}
