# Pester 5+ tests for the Windows autostart scripts. They run on Linux pwsh
# and on Windows PowerShell 5.1 (CI runs both) and never start a real
# service, create a real shortcut or register a real task: Start-Process,
# the shortcut writer and the Task Scheduler cmdlets are all mocked.
# Run: Invoke-Pester scripts/windows/tests

BeforeAll {
    $script:WinDir = Split-Path -Parent $PSScriptRoot
    $script:Marker = 'Created by second-brain-tools scripts/windows/install-autostart.ps1'

    function script:Get-FreePort {
        $l = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, 0)
        $l.Start(); $p = $l.LocalEndpoint.Port; $l.Stop(); return $p
    }
    function script:New-FakeRepo {
        $root = Join-Path ([System.IO.Path]::GetTempPath()) ('night atlas ' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path (Join-Path $root 'backend/venv/Scripts') | Out-Null
        Set-Content -LiteralPath (Join-Path $root 'backend/venv/Scripts/python.exe') -Value ''
        New-Item -ItemType Directory -Force -Path (Join-Path $root 'frontend/node_modules') | Out-Null
        return $root
    }

    # Task Scheduler cmdlets do not exist off Windows; Pester can only mock
    # commands that exist, so give it inert stand-ins there.
    foreach ($name in 'Get-ScheduledTask', 'Register-ScheduledTask', 'Unregister-ScheduledTask',
                      'New-ScheduledTaskAction', 'New-ScheduledTaskTrigger', 'New-ScheduledTaskSettingsSet',
                      'New-ScheduledTaskPrincipal') {
        if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
            # Named parameters so mocks can filter on them, as on Windows.
            New-Item -Path "function:global:$name" -Value {
                [CmdletBinding(SupportsShouldProcess = $true)]
                param($TaskName, $TaskPath, $Description, $Action, $Trigger, $Settings, $Principal, [switch]$Force,
                      $Execute, $Argument, $WorkingDirectory, [switch]$AtLogOn, $User, [switch]$AllowStartIfOnBatteries,
                      [switch]$DontStopIfGoingOnBatteries, $ExecutionTimeLimit, $MultipleInstances, $UserId, $LogonType, $RunLevel)
                throw 'stub must be mocked'
            } | Out-Null
        }
    }
}

Describe 'PowerShell syntax' {
    It 'parses <_> with no errors' -ForEach @('start-night-atlas.ps1', 'install-autostart.ps1', 'uninstall-autostart.ps1') {
        $tokens = $null; $errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile((Join-Path (Split-Path -Parent $PSScriptRoot) $_), [ref]$tokens, [ref]$errors) | Out-Null
        $errors | Should -BeNullOrEmpty
    }
}

Describe 'start-night-atlas.ps1' {
    BeforeAll {
        . (Join-Path $script:WinDir 'start-night-atlas.ps1')
    }
    BeforeEach {
        $script:Repo = New-FakeRepo
        $script:Logs = Join-Path $script:Repo 'logs'
        $script:BPort = Get-FreePort
        $script:FPort = Get-FreePort
        Mock Start-Process { [pscustomobject]@{ Id = 4242 } }
        Mock Resolve-NightAtlasBun { 'C:\fake\bun.exe' }
        Mock Start-Sleep { }
    }
    AfterEach { Remove-Item -LiteralPath $script:Repo -Recurse -Force -ErrorAction SilentlyContinue }

    It 'detects a listening port and a closed one' {
        $l = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, 0)
        $l.Start(); $p = $l.LocalEndpoint.Port
        try { Test-NightAtlasPortOpen -HostName '127.0.0.1' -Port $p | Should -BeTrue } finally { $l.Stop() }
        Test-NightAtlasPortOpen -HostName '127.0.0.1' -Port $p | Should -BeFalse
    }

    It 'DryRun starts nothing and logs both planned commands' {
        $r = Invoke-NightAtlasAutostart -RepoRoot $script:Repo -FrontendDir '' -BackendHost '127.0.0.1' -BackendPort $script:BPort `
            -FrontendPort $script:FPort -SkipBackend $false -SkipFrontend $false -StartDelaySeconds 30 -HealthTimeoutSeconds 1 `
            -LogDir $script:Logs -DryRun $true
        $r.backend | Should -Be 'dry-run'
        $r.frontend | Should -Be 'dry-run'
        Should -Invoke Start-Process -Times 0 -Exactly
        Should -Invoke Start-Sleep -Times 0 -Exactly   # no logon delay in a dry run
        $log = Get-Content -Raw (Join-Path $script:Logs 'autostart.log')
        $log | Should -Match ([regex]::Escape("-m uvicorn main:app --host 127.0.0.1 --port $($script:BPort)"))
        $log | Should -Match 'would start "C:\\fake\\bun.exe" run dev'
    }

    It 'leaves an already-listening backend alone (no duplicate, no restart)' {
        $l = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $script:BPort)
        $l.Start()
        try {
            Mock Wait-NightAtlasHealthy { $true }
            $r = Invoke-NightAtlasAutostart -RepoRoot $script:Repo -FrontendDir '' -BackendHost '127.0.0.1' -BackendPort $script:BPort `
                -FrontendPort $script:FPort -SkipBackend $false -SkipFrontend $false -StartDelaySeconds 0 -HealthTimeoutSeconds 1 `
                -LogDir $script:Logs -DryRun $false
        } finally { $l.Stop() }
        $r.backend | Should -Be 'already-running'
        $r.frontend | Should -Be 'started'
        Should -Invoke Start-Process -Times 0 -Exactly -ParameterFilter { "$ArgumentList" -like '*uvicorn*' }
        Should -Invoke Start-Process -Times 1 -Exactly -ParameterFilter { "$ArgumentList" -like '*run dev*' }
    }

    It 'starts both services hidden from the right directories with per-run logs' {
        Mock Wait-NightAtlasHealthy { $true }
        $r = Invoke-NightAtlasAutostart -RepoRoot $script:Repo -FrontendDir '' -BackendHost '127.0.0.1' -BackendPort $script:BPort `
            -FrontendPort $script:FPort -SkipBackend $false -SkipFrontend $false -StartDelaySeconds 5 -HealthTimeoutSeconds 1 `
            -LogDir $script:Logs -DryRun $false
        $r.backend | Should -Be 'started'
        $r.frontend | Should -Be 'started'
        Should -Invoke Start-Sleep -Times 1 -Exactly -ParameterFilter { $Seconds -eq 5 }
        Should -Invoke Start-Process -Times 1 -Exactly -ParameterFilter {
            $FilePath -eq 'cmd.exe' -and $WindowStyle -eq 'Hidden' -and $WorkingDirectory -like '*backend' -and
            -not $PSBoundParameters.ContainsKey('RedirectStandardOutput') -and
            "$ArgumentList" -like ('/d /c ""*venv*python.exe" -m uvicorn main:app --host 127.0.0.1 --port {0} > "*backend-*.out.log" 2> "*backend-*.err.log""' -f $script:BPort)
        }
        Should -Invoke Start-Process -Times 1 -Exactly -ParameterFilter {
            $FilePath -eq 'cmd.exe' -and "$ArgumentList" -like '/d /c ""C:\fake\bun.exe" run dev > *' -and $WorkingDirectory -like '*frontend'
        }
        Should -Invoke Wait-NightAtlasHealthy -Times 1 -Exactly -ParameterFilter { $Kind -eq 'http' -and $Port -eq $script:BPort }
        Should -Invoke Wait-NightAtlasHealthy -Times 1 -Exactly -ParameterFilter { $Kind -eq 'tcp' -and $Port -eq $script:FPort }
    }

    It 'honours -FrontendDir (a separate worktree)' {
        Mock Wait-NightAtlasHealthy { $true }
        $fe = Join-Path $script:Repo 'wt/main/frontend'
        New-Item -ItemType Directory -Force -Path (Join-Path $fe 'node_modules') | Out-Null
        Invoke-NightAtlasAutostart -RepoRoot $script:Repo -FrontendDir $fe -BackendHost '127.0.0.1' -BackendPort $script:BPort `
            -FrontendPort $script:FPort -SkipBackend $true -SkipFrontend $false -StartDelaySeconds 0 -HealthTimeoutSeconds 1 `
            -LogDir $script:Logs -DryRun $false | Out-Null
        Should -Invoke Start-Process -Times 1 -Exactly -ParameterFilter { $WorkingDirectory -eq $fe }
    }

    It 'reports failed when a service never becomes healthy' {
        Mock Wait-NightAtlasHealthy { $false }
        $r = Invoke-NightAtlasAutostart -RepoRoot $script:Repo -FrontendDir '' -BackendHost '127.0.0.1' -BackendPort $script:BPort `
            -FrontendPort $script:FPort -SkipBackend $false -SkipFrontend $true -StartDelaySeconds 0 -HealthTimeoutSeconds 1 `
            -LogDir $script:Logs -DryRun $false
        $r.backend | Should -Be 'failed'
        Get-Content -Raw (Join-Path $script:Logs 'autostart.log') | Should -Match 'not healthy'
    }

    It 'does not start the frontend without node_modules (never installs)' {
        Remove-Item -LiteralPath (Join-Path $script:Repo 'frontend/node_modules') -Recurse -Force
        $r = Invoke-NightAtlasAutostart -RepoRoot $script:Repo -FrontendDir '' -BackendHost '127.0.0.1' -BackendPort $script:BPort `
            -FrontendPort $script:FPort -SkipBackend $true -SkipFrontend $false -StartDelaySeconds 0 -HealthTimeoutSeconds 1 `
            -LogDir $script:Logs -DryRun $false
        $r.frontend | Should -Be 'failed'
        Should -Invoke Start-Process -Times 0 -Exactly
    }

    It 'never starts the backend from a git worktree' {
        Set-Content -LiteralPath (Join-Path $script:Repo '.git') -Value 'gitdir: C:/elsewhere/.git/worktrees/main'
        $r = Invoke-NightAtlasAutostart -RepoRoot $script:Repo -FrontendDir '' -BackendHost '127.0.0.1' -BackendPort $script:BPort `
            -FrontendPort $script:FPort -SkipBackend $false -SkipFrontend $true -StartDelaySeconds 0 -HealthTimeoutSeconds 1 `
            -LogDir $script:Logs -DryRun $false
        $r.backend | Should -Be 'failed'
        Should -Invoke Start-Process -Times 0 -Exactly
        Get-Content -Raw (Join-Path $script:Logs 'autostart.log') | Should -Match 'git worktree'
    }

    It 'starts the backend from a primary checkout (.git directory)' {
        Mock Wait-NightAtlasHealthy { $true }
        New-Item -ItemType Directory -Force -Path (Join-Path $script:Repo '.git') | Out-Null
        $r = Invoke-NightAtlasAutostart -RepoRoot $script:Repo -FrontendDir '' -BackendHost '127.0.0.1' -BackendPort $script:BPort `
            -FrontendPort $script:FPort -SkipBackend $false -SkipFrontend $true -StartDelaySeconds 0 -HealthTimeoutSeconds 1 `
            -LogDir $script:Logs -DryRun $false
        $r.backend | Should -Be 'started'
    }

    It 'exits without starting anything while another launcher holds the lock' {
        $sync = [hashtable]::Synchronized(@{ held = $false; release = $false })
        $ps = [powershell]::Create()
        $null = $ps.AddScript({
            param($s)
            $m = New-Object System.Threading.Mutex($false, 'NightAtlas-Autostart')
            $null = $m.WaitOne()
            $s.held = $true
            while (-not $s.release) { [System.Threading.Thread]::Sleep(50) }
            $m.ReleaseMutex(); $m.Dispose()
        }).AddArgument($sync)
        $handle = $ps.BeginInvoke()
        try {
            $deadline = (Get-Date).AddSeconds(10)
            while (-not $sync.held -and (Get-Date) -lt $deadline) { [System.Threading.Thread]::Sleep(50) }
            $sync.held | Should -BeTrue
            $r = Invoke-NightAtlasAutostart -RepoRoot $script:Repo -FrontendDir '' -BackendHost '127.0.0.1' -BackendPort $script:BPort `
                -FrontendPort $script:FPort -SkipBackend $false -SkipFrontend $false -StartDelaySeconds 0 -HealthTimeoutSeconds 1 `
                -LogDir $script:Logs -DryRun $false
            $r.locked | Should -BeTrue
            Should -Invoke Start-Process -Times 0 -Exactly
        } finally {
            $sync.release = $true
            $ps.EndInvoke($handle) | Out-Null
            $ps.Dispose()
        }
    }
}

Describe 'install-autostart.ps1' {
    BeforeAll {
        . (Join-Path $script:WinDir 'install-autostart.ps1')
    }
    BeforeEach {
        $script:Repo = New-FakeRepo
        $script:Startup = Join-Path $script:Repo 'Startup'
        New-Item -ItemType Directory -Force -Path $script:Startup | Out-Null
        Mock New-NightAtlasShortcut { }
        Mock Get-ScheduledTask { $null }
        # The real cmdlet types these as CIM instances; the mocked builders return strings.
        Mock Register-ScheduledTask { } -RemoveParameterType Action, Trigger, Settings, Principal
        Mock New-ScheduledTaskAction { 'action' }
        Mock New-ScheduledTaskTrigger { 'trigger' }
        Mock New-ScheduledTaskSettingsSet { 'settings' }
        Mock New-ScheduledTaskPrincipal { 'principal' }
    }
    AfterEach { Remove-Item -LiteralPath $script:Repo -Recurse -Force -ErrorAction SilentlyContinue }

    It 'builds a wscript launch line that quotes paths with spaces' {
        $spec = Get-NightAtlasLaunchSpec -ScriptDir $script:WinDir -RepoRoot 'C:\Users\me\git\second brain' -FrontendDir 'C:\wt\main\frontend' `
            -BackendPort 8000 -FrontendPort 3000 -StartDelaySeconds 20
        $spec.Execute | Should -Be 'wscript.exe'
        $spec.Arguments | Should -Match '-RepoRoot "C:\\Users\\me\\git\\second brain"'
        $spec.Arguments | Should -Match '-FrontendDir C:\\wt\\main\\frontend'
        $spec.Arguments | Should -Match '-BackendPort 8000 -FrontendPort 3000 -StartDelaySeconds 20$'
        $spec.Arguments | Should -Match 'start-night-atlas-hidden\.vbs'
    }

    It 'refuses a checkout without backend\' {
        Remove-Item -LiteralPath (Join-Path $script:Repo 'backend') -Recurse -Force
        { Install-NightAtlasAutostart -Method StartupFolder -ScriptDir $script:WinDir -RepoRoot $script:Repo -FrontendDir '' `
            -BackendPort 8000 -FrontendPort 3000 -StartDelaySeconds 20 -StartupDir $script:Startup -DryRun $false } | Should -Throw '*backend*'
        Should -Invoke New-NightAtlasShortcut -Times 0 -Exactly
    }

    It 'refuses a worktree as -RepoRoot' {
        Set-Content -LiteralPath (Join-Path $script:Repo '.git') -Value 'gitdir: C:/elsewhere'
        { Install-NightAtlasAutostart -Method Task -ScriptDir $script:WinDir -RepoRoot $script:Repo -FrontendDir '' `
            -BackendPort 8000 -FrontendPort 3000 -StartDelaySeconds 20 -StartupDir $script:Startup -DryRun $false } | Should -Throw '*worktree*'
        Should -Invoke Register-ScheduledTask -Times 0 -Exactly
    }

    It 'DryRun writes nothing' {
        $r = Install-NightAtlasAutostart -Method StartupFolder -ScriptDir $script:WinDir -RepoRoot $script:Repo -FrontendDir '' `
            -BackendPort 8000 -FrontendPort 3000 -StartDelaySeconds 20 -StartupDir $script:Startup -DryRun $true
        $r.Changed | Should -BeFalse
        Should -Invoke New-NightAtlasShortcut -Times 0 -Exactly
        Should -Invoke Register-ScheduledTask -Times 0 -Exactly
    }

    It '-WhatIf writes nothing' {
        $r = Install-NightAtlasAutostart -Method StartupFolder -ScriptDir $script:WinDir -RepoRoot $script:Repo -FrontendDir '' `
            -BackendPort 8000 -FrontendPort 3000 -StartDelaySeconds 20 -StartupDir $script:Startup -DryRun $false -WhatIf
        $r.Changed | Should -BeFalse
        Should -Invoke New-NightAtlasShortcut -Times 0 -Exactly
    }

    It 'StartupFolder writes one marked shortcut and does not register any task' {
        $r = Install-NightAtlasAutostart -Method StartupFolder -ScriptDir $script:WinDir -RepoRoot $script:Repo -FrontendDir '' `
            -BackendPort 8000 -FrontendPort 3000 -StartDelaySeconds 20 -StartupDir $script:Startup -DryRun $false
        $r.Changed | Should -BeTrue
        Should -Invoke New-NightAtlasShortcut -Times 1 -Exactly -ParameterFilter {
            $Path -like '*NightAtlas-Autostart.lnk' -and $Description -eq $script:Marker -and $Spec.Execute -eq 'wscript.exe'
        }
        Should -Invoke Register-ScheduledTask -Times 0 -Exactly
    }

    It 'will not overwrite a same-named shortcut it did not create' {
        Set-Content -LiteralPath (Join-Path $script:Startup 'NightAtlas-Autostart.lnk') -Value 'x'
        Mock Get-NightAtlasShortcutDescription { 'someone else' }
        { Install-NightAtlasAutostart -Method StartupFolder -ScriptDir $script:WinDir -RepoRoot $script:Repo -FrontendDir '' `
            -BackendPort 8000 -FrontendPort 3000 -StartDelaySeconds 20 -StartupDir $script:Startup -DryRun $false } | Should -Throw '*not created by this installer*'
        Should -Invoke New-NightAtlasShortcut -Times 0 -Exactly
    }

    It 're-running over its own shortcut is idempotent' {
        Set-Content -LiteralPath (Join-Path $script:Startup 'NightAtlas-Autostart.lnk') -Value 'x'
        Mock Get-NightAtlasShortcutDescription { $script:Marker }
        $r = Install-NightAtlasAutostart -Method StartupFolder -ScriptDir $script:WinDir -RepoRoot $script:Repo -FrontendDir '' `
            -BackendPort 8000 -FrontendPort 3000 -StartDelaySeconds 20 -StartupDir $script:Startup -DryRun $false
        $r.Changed | Should -BeTrue
        Should -Invoke New-NightAtlasShortcut -Times 1 -Exactly
    }

    It 'Task method registers only NightAtlas-Autostart and only looks that one name up' {
        $r = Install-NightAtlasAutostart -Method Task -ScriptDir $script:WinDir -RepoRoot $script:Repo -FrontendDir '' `
            -BackendPort 8000 -FrontendPort 3000 -StartDelaySeconds 20 -StartupDir $script:Startup -DryRun $false
        $r.Changed | Should -BeTrue
        Should -Invoke Register-ScheduledTask -Times 1 -Exactly -ParameterFilter {
            $TaskName -eq 'NightAtlas-Autostart' -and $TaskPath -eq '\' -and $Description -eq $script:Marker
        }
        Should -Invoke Get-ScheduledTask -Times 0 -Exactly -ParameterFilter { $TaskName -ne 'NightAtlas-Autostart' }
        Should -Invoke New-ScheduledTaskSettingsSet -Times 1 -Exactly -ParameterFilter { $MultipleInstances -eq 'IgnoreNew' }
    }

    It 'Task method refuses a same-named task it did not create' {
        Mock Get-ScheduledTask { [pscustomobject]@{ TaskName = 'NightAtlas-Autostart'; Description = 'other' } }
        { Install-NightAtlasAutostart -Method Task -ScriptDir $script:WinDir -RepoRoot $script:Repo -FrontendDir '' `
            -BackendPort 8000 -FrontendPort 3000 -StartDelaySeconds 20 -StartupDir $script:Startup -DryRun $false } | Should -Throw '*did not create*'
        Should -Invoke Register-ScheduledTask -Times 0 -Exactly
    }
}

Describe 'uninstall-autostart.ps1' {
    BeforeAll {
        . (Join-Path $script:WinDir 'uninstall-autostart.ps1')
    }
    BeforeEach {
        $script:Startup = Join-Path ([System.IO.Path]::GetTempPath()) ('startup-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path $script:Startup | Out-Null
        $script:Lnk = Join-Path $script:Startup 'NightAtlas-Autostart.lnk'
        Set-Content -LiteralPath $script:Lnk -Value 'x'
        Mock Get-NightAtlasShortcutDescription { $script:Marker }
        Mock Get-ScheduledTask { $null }
        Mock Unregister-ScheduledTask { }
    }
    AfterEach { Remove-Item -LiteralPath $script:Startup -Recurse -Force -ErrorAction SilentlyContinue }

    It 'DryRun removes nothing' {
        Mock Get-ScheduledTask { [pscustomobject]@{ Description = $script:Marker } }
        Uninstall-NightAtlasAutostart -Method All -StartupDir $script:Startup -DryRun $true | Out-Null
        Test-Path -LiteralPath $script:Lnk | Should -BeTrue
        Should -Invoke Unregister-ScheduledTask -Times 0 -Exactly
    }

    It 'removes its own shortcut and task' {
        Mock Get-ScheduledTask { [pscustomobject]@{ Description = $script:Marker } }
        $r = Uninstall-NightAtlasAutostart -Method All -StartupDir $script:Startup -DryRun $false
        Test-Path -LiteralPath $script:Lnk | Should -BeFalse
        Should -Invoke Unregister-ScheduledTask -Times 1 -Exactly -ParameterFilter { $TaskName -eq 'NightAtlas-Autostart' }
        Should -Invoke Get-ScheduledTask -Times 0 -Exactly -ParameterFilter { $TaskName -ne 'NightAtlas-Autostart' }
        $r.Count | Should -Be 2
    }

    It 'leaves entries it did not create' {
        Mock Get-NightAtlasShortcutDescription { 'other' }
        Mock Get-ScheduledTask { [pscustomobject]@{ Description = 'other' } }
        Uninstall-NightAtlasAutostart -Method All -StartupDir $script:Startup -DryRun $false 3>$null | Out-Null
        Test-Path -LiteralPath $script:Lnk | Should -BeTrue
        Should -Invoke Unregister-ScheduledTask -Times 0 -Exactly
    }
}
