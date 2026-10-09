<#
.SYNOPSIS
    Start the Night Atlas backend (uvicorn on :8000) and frontend (Next.js on
    :3000) in the background, once, at Windows logon.

.DESCRIPTION
    Meant to be launched by the logon entry that install-autostart.ps1 creates,
    but safe to run by hand. For each service it first checks whether anything
    already answers on the port; if so it logs that and leaves it alone, so a
    backend you started yourself is never duplicated or restarted. Otherwise it
    starts the service hidden, with stdout/stderr in per-run log files, and
    waits until the port answers (and, for the backend, GET /api/health).

    It never stops, restarts or kills anything, never installs dependencies,
    and never touches Task Scheduler.

    -DryRun logs exactly what would be started and starts nothing.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\start-night-atlas.ps1 -DryRun
#>
[CmdletBinding()]
param(
    # Checkout that holds backend\ (and frontend\ unless -FrontendDir is given).
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    # Frontend directory; defaults to <RepoRoot>\frontend.
    [string]$FrontendDir = '',
    [string]$BackendHost = '127.0.0.1',
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    # Wait this long before doing anything, so OneDrive and the network settle after logon.
    [int]$StartDelaySeconds = 0,
    [int]$HealthTimeoutSeconds = 180,
    [string]$LogDir = '',
    [switch]$DryRun
)

Set-StrictMode -Version 2.0

function Get-NightAtlasDefaultLogDir {
    $base = $env:LOCALAPPDATA
    if (-not $base) { $base = [System.IO.Path]::GetTempPath() }
    return (Join-Path (Join-Path $base 'NightAtlas') 'logs')
}

function Write-NightAtlasLog {
    param([string]$Message, [string]$Level = 'INFO')
    $line = '{0} [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    # Write-Host, not Write-Output: callers return status strings, and log
    # lines on the output stream would end up in those return values.
    Write-Host $line
    if ($script:NightAtlasLogFile) {
        try { Add-Content -LiteralPath $script:NightAtlasLogFile -Value $line -Encoding UTF8 } catch { }
    }
}

function Test-NightAtlasPortOpen {
    # True when something accepts TCP connections on host:port. Works on any
    # PowerShell (no Get-NetTCPConnection), and catches a listener on 0.0.0.0.
    param([string]$HostName = '127.0.0.1', [int]$Port, [int]$TimeoutMs = 750)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Test-NightAtlasBackendHealthy {
    param([string]$HostName, [int]$Port)
    try {
        $r = Invoke-WebRequest -Uri ('http://{0}:{1}/api/health' -f $HostName, $Port) -UseBasicParsing -TimeoutSec 5
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Resolve-NightAtlasPython {
    param([string]$BackendDir)
    foreach ($rel in @('venv\Scripts\python.exe', '.venv\Scripts\python.exe', 'venv/bin/python', '.venv/bin/python')) {
        $candidate = Join-Path $BackendDir $rel
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { return $cmd.Source }
    return $null
}

function Resolve-NightAtlasBun {
    $cmd = Get-Command bun -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd) { return $cmd.Source }
    $home_ = $env:USERPROFILE
    if (-not $home_) { $home_ = $HOME }
    foreach ($rel in @('scoop\shims\bun.exe', '.bun\bin\bun.exe')) {
        $candidate = Join-Path $home_ $rel
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function Test-NightAtlasHealthy {
    param([string]$Kind, [string]$HostName, [int]$Port)
    if ($Kind -eq 'http') { return (Test-NightAtlasBackendHealthy -HostName $HostName -Port $Port) }
    return (Test-NightAtlasPortOpen -HostName $HostName -Port $Port)
}

function Wait-NightAtlasHealthy {
    param([string]$Kind, [string]$HostName, [int]$Port, [int]$TimeoutSeconds, [int]$IntervalSeconds = 2)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-NightAtlasHealthy -Kind $Kind -HostName $HostName -Port $Port) { return $true }
        Start-Sleep -Seconds $IntervalSeconds
    }
    return (Test-NightAtlasHealthy -Kind $Kind -HostName $HostName -Port $Port)
}

function Start-NightAtlasService {
    # Returns one of: already-running, dry-run, started, failed, skipped.
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [int]$Port,
        [string]$ProbeHost,
        # 'http' waits for GET /api/health, 'tcp' for the port to accept connections.
        [ValidateSet('http', 'tcp')][string]$HealthKind = 'tcp',
        [int]$TimeoutSeconds,
        [string]$LogDirectory,
        [string]$Stamp,
        [switch]$DryRun
    )
    if (Test-NightAtlasPortOpen -HostName $ProbeHost -Port $Port) {
        Write-NightAtlasLog "$Name : port $Port already answering; leaving it alone (no duplicate, no restart)."
        return 'already-running'
    }
    if (-not $FilePath) {
        Write-NightAtlasLog "$Name : executable not found; not starting." 'ERROR'
        return 'failed'
    }
    if (-not (Test-Path -LiteralPath $WorkingDirectory)) {
        Write-NightAtlasLog "$Name : working directory '$WorkingDirectory' does not exist; not starting." 'ERROR'
        return 'failed'
    }
    $out = Join-Path $LogDirectory ('{0}-{1}.out.log' -f $Name, $Stamp)
    $err = Join-Path $LogDirectory ('{0}-{1}.err.log' -f $Name, $Stamp)
    $display = '"{0}" {1}  (cwd {2})' -f $FilePath, ($ArgumentList -join ' '), $WorkingDirectory
    if ($DryRun) {
        Write-NightAtlasLog "$Name : DRY RUN, would start $display; logs $out"
        return 'dry-run'
    }
    Write-NightAtlasLog "$Name : starting $display; logs $out"
    try {
        $proc = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -WorkingDirectory $WorkingDirectory `
            -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err -PassThru -ErrorAction Stop
    } catch {
        Write-NightAtlasLog "$Name : Start-Process failed: $($_.Exception.Message)" 'ERROR'
        return 'failed'
    }
    $pidText = ''
    if ($proc) { $pidText = " pid $($proc.Id)" }
    $ok = Wait-NightAtlasHealthy -Kind $HealthKind -HostName $ProbeHost -Port $Port -TimeoutSeconds $TimeoutSeconds
    if ($ok) {
        Write-NightAtlasLog "$Name : up on port $Port$pidText."
        return 'started'
    }
    Write-NightAtlasLog "$Name : launched$pidText but not healthy after $TimeoutSeconds s; see $err" 'WARN'
    return 'failed'
}

function Remove-NightAtlasOldLogs {
    param([string]$LogDirectory, [int]$Keep = 20)
    try {
        Get-ChildItem -LiteralPath $LogDirectory -Filter '*-*.???.log' -ErrorAction Stop |
            Sort-Object LastWriteTime -Descending | Select-Object -Skip $Keep |
            Remove-Item -Force -ErrorAction SilentlyContinue
    } catch { }
}

function Invoke-NightAtlasAutostart {
    param(
        [string]$RepoRoot, [string]$FrontendDir, [string]$BackendHost, [int]$BackendPort,
        [int]$FrontendPort, [bool]$SkipBackend, [bool]$SkipFrontend, [int]$StartDelaySeconds,
        [int]$HealthTimeoutSeconds, [string]$LogDir, [bool]$DryRun
    )
    if (-not $LogDir) { $LogDir = Get-NightAtlasDefaultLogDir }
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    $script:NightAtlasLogFile = Join-Path $LogDir 'autostart.log'
    if (-not $FrontendDir) { $FrontendDir = Join-Path $RepoRoot 'frontend' }
    $backendDir = Join-Path $RepoRoot 'backend'
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

    # One launcher at a time: a double logon entry or a manual run during the
    # logon run must not race two backends onto :8000.
    $mutex = New-Object System.Threading.Mutex($false, 'NightAtlas-Autostart')
    $owned = $false
    try {
        try { $owned = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $owned = $true }
        if (-not $owned) {
            Write-NightAtlasLog 'Another Night Atlas launcher is already running; exiting.' 'WARN'
            return @{ backend = 'skipped'; frontend = 'skipped'; locked = $true }
        }
        $mode = ''
        if ($DryRun) { $mode = ' (dry run)' }
        Write-NightAtlasLog "Night Atlas autostart$mode : repo=$RepoRoot frontend=$FrontendDir"
        if ($StartDelaySeconds -gt 0 -and -not $DryRun) {
            Write-NightAtlasLog "Waiting $StartDelaySeconds s for logon to settle."
            Start-Sleep -Seconds $StartDelaySeconds
        }
        $result = @{ backend = 'skipped'; frontend = 'skipped'; locked = $false }

        if (-not $SkipBackend) {
            $python = Resolve-NightAtlasPython -BackendDir $backendDir
            $result.backend = Start-NightAtlasService -Name 'backend' -FilePath $python `
                -ArgumentList @('-m', 'uvicorn', 'main:app', '--host', $BackendHost, '--port', "$BackendPort") `
                -WorkingDirectory $backendDir -Port $BackendPort -ProbeHost $BackendHost `
                -HealthKind 'http' `
                -TimeoutSeconds $HealthTimeoutSeconds -LogDirectory $LogDir -Stamp $stamp -DryRun:$DryRun
        }
        if (-not $SkipFrontend) {
            $bun = Resolve-NightAtlasBun
            if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir 'node_modules'))) {
                Write-NightAtlasLog "frontend : $FrontendDir has no node_modules; run 'bun install' there once. Not starting." 'ERROR'
                $result.frontend = 'failed'
            } else {
                $result.frontend = Start-NightAtlasService -Name 'frontend' -FilePath $bun `
                    -ArgumentList @('run', 'dev') -WorkingDirectory $FrontendDir -Port $FrontendPort -ProbeHost '127.0.0.1' `
                    -HealthKind 'tcp' `
                    -TimeoutSeconds $HealthTimeoutSeconds -LogDirectory $LogDir -Stamp $stamp -DryRun:$DryRun
            }
        }
        if (-not $DryRun) { Remove-NightAtlasOldLogs -LogDirectory $LogDir }
        Write-NightAtlasLog ('Done: backend={0} frontend={1}' -f $result.backend, $result.frontend)
        return $result
    } finally {
        if ($owned) { $mutex.ReleaseMutex() }
        $mutex.Dispose()
    }
}

# Dot-sourcing (the Pester tests) loads the functions without running anything.
if ($MyInvocation.InvocationName -ne '.') {
    $r = Invoke-NightAtlasAutostart -RepoRoot $RepoRoot -FrontendDir $FrontendDir -BackendHost $BackendHost `
        -BackendPort $BackendPort -FrontendPort $FrontendPort -SkipBackend ([bool]$SkipBackend) `
        -SkipFrontend ([bool]$SkipFrontend) -StartDelaySeconds $StartDelaySeconds `
        -HealthTimeoutSeconds $HealthTimeoutSeconds -LogDir $LogDir -DryRun ([bool]$DryRun)
    if ($r.backend -eq 'failed' -or $r.frontend -eq 'failed') { exit 1 }
    exit 0
}
