# End-to-end tests for the autostart scripts on a real Windows box: a real
# (tiny) uvicorn backend, the real VBS wrapper, a real .lnk and a real logon
# task. Only for a throwaway machine (the CI windows runner): they start and
# kill processes and register/unregister the task 'NightAtlas-Autostart'.
# Opt in with NIGHTATLAS_E2E=1; skipped everywhere else.

BeforeDiscovery {
    $script:RunE2E = ($env:NIGHTATLAS_E2E -eq '1') -and ($env:OS -eq 'Windows_NT')
}

Describe 'Windows autostart end to end' -Skip:(-not $script:RunE2E) {
    BeforeAll {
        $script:WinDir = Split-Path -Parent $PSScriptRoot
        $script:Marker = 'Created by second-brain-tools scripts/windows/install-autostart.ps1'
        function script:Get-FreePort {
            $l = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, 0)
            $l.Start(); $p = $l.LocalEndpoint.Port; $l.Stop(); return $p
        }
        function script:Test-Health([int]$Port) {
            try { return ((Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) } catch { return $false }
        }
        # A checkout-shaped temp dir with a space in it, a real venv and a
        # minimal ASGI app that answers /api/health like the real backend.
        $script:Repo = Join-Path $env:RUNNER_TEMP ('night atlas e2e ' + [guid]::NewGuid().ToString('N').Substring(0, 8))
        New-Item -ItemType Directory -Force -Path (Join-Path $script:Repo 'backend'), (Join-Path $script:Repo 'frontend') | Out-Null
        Set-Content -LiteralPath (Join-Path $script:Repo 'backend\main.py') -Encoding ASCII -Value @'
async def app(scope, receive, send):
    if scope["type"] != "http":
        return
    ok = scope["path"] == "/api/health"
    await send({"type": "http.response.start", "status": 200 if ok else 404,
                "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": b'{"data": {}, "is_scanning": false, "last_scan_time": 0}'})
'@
        & python -m venv (Join-Path $script:Repo 'backend\venv')
        & (Join-Path $script:Repo 'backend\venv\Scripts\python.exe') -m pip install -q 'uvicorn==0.51.0'
        $script:Ports = @()
        # Run a script in a separate powershell.exe and wait for that process
        # only (not its children, which the launcher leaves running).
        function script:Invoke-Ps([string]$File, [string[]]$Arguments) {
            $argv = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $File + '"')) + @($Arguments | ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } })
            $p = Start-Process -FilePath 'powershell.exe' -ArgumentList $argv -WindowStyle Hidden -PassThru
            $null = $p.Handle
            if (-not $p.WaitForExit(300000)) { $p.Kill(); throw "$File timed out" }
            return $p.ExitCode
        }
    }
    AfterAll {
        foreach ($p in $script:Ports) {
            Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*--port $p*" } |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        }
        if (Get-ScheduledTask -TaskName 'NightAtlas-Autostart' -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName 'NightAtlas-Autostart' -Confirm:$false
        }
    }

    It 'starts the backend hidden, waits for /api/health, and does not start a second one' {
        $port = Get-FreePort; $script:Ports += $port
        $logs = Join-Path $script:Repo 'logs-a'
        $launcher = Join-Path $script:WinDir 'start-night-atlas.ps1'
        Invoke-Ps $launcher @('-RepoRoot', $script:Repo, '-SkipFrontend', '-BackendPort', "$port", '-LogDir', $logs, '-HealthTimeoutSeconds', '120') | Should -Be 0
        Test-Health $port | Should -BeTrue
        (Get-Content -Raw (Join-Path $logs 'autostart.log')) | Should -Match "backend : up on port $port"

        Invoke-Ps $launcher @('-RepoRoot', $script:Repo, '-SkipFrontend', '-BackendPort', "$port", '-LogDir', $logs, '-HealthTimeoutSeconds', '120') | Should -Be 0
        (Get-Content -Raw (Join-Path $logs 'autostart.log')) | Should -Match "port $port already answering"
        @(Get-ChildItem -LiteralPath $logs -Filter 'backend-*.out.log').Count | Should -Be 1
    }

    It 'DryRun starts nothing' {
        $port = Get-FreePort
        $logs = Join-Path $script:Repo 'logs-dry'
        Invoke-Ps (Join-Path $script:WinDir 'start-night-atlas.ps1') @('-RepoRoot', $script:Repo, '-SkipFrontend', '-BackendPort', "$port", '-LogDir', $logs, '-DryRun') | Should -Be 0
        Start-Sleep -Seconds 3
        Test-Health $port | Should -BeFalse
        (Get-Content -Raw (Join-Path $logs 'autostart.log')) | Should -Match 'DRY RUN'
    }

    It 'the hidden VBS wrapper passes arguments with spaces through' {
        $port = Get-FreePort; $script:Ports += $port
        $logs = Join-Path $script:Repo 'logs vbs'
        & wscript.exe (Join-Path $script:WinDir 'start-night-atlas-hidden.vbs') -RepoRoot $script:Repo -SkipFrontend `
            -BackendPort $port -LogDir $logs -HealthTimeoutSeconds 120
        $deadline = (Get-Date).AddSeconds(150)
        while (-not (Test-Health $port) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
        Test-Health $port | Should -BeTrue
        Test-Path -LiteralPath (Join-Path $logs 'autostart.log') | Should -BeTrue
    }

    It 'installs and uninstalls a real Startup shortcut' {
        $startup = Join-Path $script:Repo 'Startup'
        New-Item -ItemType Directory -Force -Path $startup | Out-Null
        Invoke-Ps (Join-Path $script:WinDir 'install-autostart.ps1') @('-RepoRoot', $script:Repo, '-StartupDir', $startup) | Should -Be 0
        $lnkPath = Join-Path $startup 'NightAtlas-Autostart.lnk'
        $lnk = (New-Object -ComObject WScript.Shell).CreateShortcut($lnkPath)
        $lnk.TargetPath | Should -Match 'wscript\.exe$'
        $lnk.Arguments | Should -Match 'start-night-atlas-hidden\.vbs'
        $lnk.Arguments | Should -Match ([regex]::Escape('"' + $script:Repo + '"'))
        $lnk.Description | Should -Be $script:Marker
        # Idempotent re-run.
        Invoke-Ps (Join-Path $script:WinDir 'install-autostart.ps1') @('-RepoRoot', $script:Repo, '-StartupDir', $startup) | Should -Be 0
        Invoke-Ps (Join-Path $script:WinDir 'uninstall-autostart.ps1') @('-Method', 'StartupFolder', '-StartupDir', $startup) | Should -Be 0
        Test-Path -LiteralPath $lnkPath | Should -BeFalse
    }

    It 'installs and uninstalls a real logon task without touching other tasks' {
        $before = @(Get-ScheduledTask | ForEach-Object { $_.TaskPath + $_.TaskName }) | Sort-Object
        Invoke-Ps (Join-Path $script:WinDir 'install-autostart.ps1') @('-Method', 'Task', '-RepoRoot', $script:Repo) | Should -Be 0
        $t = Get-ScheduledTask -TaskName 'NightAtlas-Autostart' -TaskPath '\'
        $t.Description | Should -Be $script:Marker
        $t.Actions[0].Execute | Should -Be 'wscript.exe'
        $t.State | Should -Not -Be 'Running'   # installing starts nothing
        Invoke-Ps (Join-Path $script:WinDir 'uninstall-autostart.ps1') @('-Method', 'Task') | Should -Be 0
        Get-ScheduledTask -TaskName 'NightAtlas-Autostart' -ErrorAction SilentlyContinue | Should -BeNullOrEmpty
        $after = @(Get-ScheduledTask | ForEach-Object { $_.TaskPath + $_.TaskName }) | Sort-Object
        Compare-Object $before $after | Should -BeNullOrEmpty
    }
}
