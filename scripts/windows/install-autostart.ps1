<#
.SYNOPSIS
    Make the Night Atlas backend and frontend start when you log into Windows.

.DESCRIPTION
    Adds ONE logon entry named 'NightAtlas-Autostart' that runs
    start-night-atlas-hidden.vbs -> start-night-atlas.ps1 from this checkout.

    -Method StartupFolder (default) writes NightAtlas-Autostart.lnk into your
    Startup folder: no admin rights, and nothing in Task Scheduler changes.
    -Method Task registers a Task Scheduler task with that one name instead
    (may need an elevated prompt for a logon trigger).

    Idempotent: re-running replaces only its own entry. It never reads,
    changes or removes any other scheduled task or shortcut, and refuses to
    overwrite an entry of the same name that it did not create.
    Installing does NOT start anything; the services start at the next logon
    (or run start-night-atlas.ps1 yourself).

    -DryRun (or -WhatIf) prints what would be installed and changes nothing.
    Undo with uninstall-autostart.ps1.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\install-autostart.ps1 -DryRun
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet('StartupFolder', 'Task')][string]$Method = 'StartupFolder',
    [string]$RepoRoot = (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)),
    [string]$FrontendDir = '',
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [int]$StartDelaySeconds = 20,
    [string]$StartupDir = '',
    [switch]$DryRun
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$script:NightAtlasEntryName = 'NightAtlas-Autostart'
$script:NightAtlasMarker = 'Created by second-brain-tools scripts/windows/install-autostart.ps1'

function Get-NightAtlasStartupDir {
    param([string]$StartupDir)
    if ($StartupDir) { return $StartupDir }
    return (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup')
}

function ConvertTo-NightAtlasArgument {
    param([string]$Value)
    if ($Value -match '\s') { return '"' + $Value + '"' }
    return $Value
}

function Get-NightAtlasLaunchSpec {
    # What the logon entry runs: wscript.exe <vbs> <launcher args>.
    param([string]$ScriptDir, [string]$RepoRoot, [string]$FrontendDir, [int]$BackendPort,
          [int]$FrontendPort, [int]$StartDelaySeconds)
    $vbs = Join-Path $ScriptDir 'start-night-atlas-hidden.vbs'
    $parts = @((ConvertTo-NightAtlasArgument $vbs), '-RepoRoot', (ConvertTo-NightAtlasArgument $RepoRoot))
    if ($FrontendDir) { $parts += @('-FrontendDir', (ConvertTo-NightAtlasArgument $FrontendDir)) }
    $parts += @('-BackendPort', "$BackendPort", '-FrontendPort', "$FrontendPort", '-StartDelaySeconds', "$StartDelaySeconds")
    return [pscustomobject]@{
        Execute          = 'wscript.exe'
        Arguments        = ($parts -join ' ')
        WorkingDirectory = $RepoRoot
        Vbs              = $vbs
    }
}

function Assert-NightAtlasLayout {
    param([string]$ScriptDir, [string]$RepoRoot, [string]$FrontendDir)
    foreach ($f in @('start-night-atlas.ps1', 'start-night-atlas-hidden.vbs')) {
        if (-not (Test-Path -LiteralPath (Join-Path $ScriptDir $f))) { throw "Missing $f next to this installer ($ScriptDir)." }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot 'backend'))) { throw "No backend\ under -RepoRoot '$RepoRoot'." }
    # The backend must come from the primary checkout (the live index); a
    # linked worktree has a .git file and an empty backend\chroma_db.
    if (Test-Path -LiteralPath (Join-Path $RepoRoot '.git') -PathType Leaf) {
        throw "-RepoRoot '$RepoRoot' is a git worktree; point it at the primary checkout (use -FrontendDir for a worktree frontend)."
    }
    $fe = $FrontendDir
    if (-not $fe) { $fe = Join-Path $RepoRoot 'frontend' }
    if (-not (Test-Path -LiteralPath $fe)) { throw "Frontend directory '$fe' does not exist (pass -FrontendDir)." }
}

function Get-NightAtlasShortcutDescription {
    param([string]$Path)
    $shell = New-Object -ComObject WScript.Shell
    return $shell.CreateShortcut($Path).Description
}

function New-NightAtlasShortcut {
    param([string]$Path, $Spec, [string]$Description)
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($Path)
    $lnk.TargetPath = $Spec.Execute
    $lnk.Arguments = $Spec.Arguments
    $lnk.WorkingDirectory = $Spec.WorkingDirectory
    $lnk.Description = $Description
    $lnk.WindowStyle = 7  # minimized; wscript shows no window anyway
    $lnk.Save()
}

function Get-NightAtlasOwnTask {
    # Looks up exactly one task by name; never enumerates or touches others.
    return (Get-ScheduledTask -TaskName $script:NightAtlasEntryName -TaskPath '\' -ErrorAction SilentlyContinue)
}

function Install-NightAtlasAutostart {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param([string]$Method, [string]$ScriptDir, [string]$RepoRoot, [string]$FrontendDir, [int]$BackendPort,
          [int]$FrontendPort, [int]$StartDelaySeconds, [string]$StartupDir, [bool]$DryRun)

    Assert-NightAtlasLayout -ScriptDir $ScriptDir -RepoRoot $RepoRoot -FrontendDir $FrontendDir
    $spec = Get-NightAtlasLaunchSpec -ScriptDir $ScriptDir -RepoRoot $RepoRoot -FrontendDir $FrontendDir `
        -BackendPort $BackendPort -FrontendPort $FrontendPort -StartDelaySeconds $StartDelaySeconds
    $prefix = ''
    if ($DryRun) { $prefix = 'DRY RUN: ' }

    if ($Method -eq 'StartupFolder') {
        $dir = Get-NightAtlasStartupDir -StartupDir $StartupDir
        $lnk = Join-Path $dir ($script:NightAtlasEntryName + '.lnk')
        if (Test-Path -LiteralPath $lnk) {
            $desc = Get-NightAtlasShortcutDescription -Path $lnk
            if ($desc -ne $script:NightAtlasMarker) { throw "$lnk exists and was not created by this installer; not overwriting." }
        }
        Write-Host ("{0}Startup shortcut {1}`n  target: {2} {3}`n  cwd:    {4}" -f $prefix, $lnk, $spec.Execute, $spec.Arguments, $spec.WorkingDirectory)
        if ($DryRun) { return [pscustomobject]@{ Method = $Method; Path = $lnk; Spec = $spec; Changed = $false } }
        if ($PSCmdlet.ShouldProcess($lnk, 'Create Night Atlas startup shortcut')) {
            New-NightAtlasShortcut -Path $lnk -Spec $spec -Description $script:NightAtlasMarker
            if (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue) {
                if (Get-NightAtlasOwnTask) { Write-Warning "A '$($script:NightAtlasEntryName)' task also exists; remove it with uninstall-autostart.ps1 -Method Task to avoid two entries (the launcher still won't double-start)." }
            }
            return [pscustomobject]@{ Method = $Method; Path = $lnk; Spec = $spec; Changed = $true }
        }
        return [pscustomobject]@{ Method = $Method; Path = $lnk; Spec = $spec; Changed = $false }
    }

    # Method Task: one task, one name, current user, at logon, no elevation.
    $existing = Get-NightAtlasOwnTask
    if ($existing -and ($existing.Description -ne $script:NightAtlasMarker)) {
        throw "A scheduled task named '$($script:NightAtlasEntryName)' exists that this installer did not create; not touching it."
    }
    $user = if ($env:USERDOMAIN) { "$env:USERDOMAIN\$env:USERNAME" } else { $env:USERNAME }
    Write-Host ("{0}Scheduled task \{1} (at logon of {2})`n  action: {3} {4}`n  cwd:    {5}" -f $prefix, $script:NightAtlasEntryName, $user, $spec.Execute, $spec.Arguments, $spec.WorkingDirectory)
    if ($DryRun) { return [pscustomobject]@{ Method = $Method; Path = "\$($script:NightAtlasEntryName)"; Spec = $spec; Changed = $false } }
    if ($PSCmdlet.ShouldProcess("\$($script:NightAtlasEntryName)", 'Register Night Atlas logon task')) {
        $action = New-ScheduledTaskAction -Execute $spec.Execute -Argument $spec.Arguments -WorkingDirectory $spec.WorkingDirectory
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
        $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $script:NightAtlasEntryName -TaskPath '\' -Description $script:NightAtlasMarker `
            -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
        return [pscustomobject]@{ Method = $Method; Path = "\$($script:NightAtlasEntryName)"; Spec = $spec; Changed = $true }
    }
    return [pscustomobject]@{ Method = $Method; Path = "\$($script:NightAtlasEntryName)"; Spec = $spec; Changed = $false }
}

if ($MyInvocation.InvocationName -ne '.') {
    $r = Install-NightAtlasAutostart -Method $Method -ScriptDir $PSScriptRoot -RepoRoot $RepoRoot -FrontendDir $FrontendDir `
        -BackendPort $BackendPort -FrontendPort $FrontendPort -StartDelaySeconds $StartDelaySeconds `
        -StartupDir $StartupDir -DryRun ([bool]$DryRun) -WhatIf:$WhatIfPreference
    if ($r.Changed) {
        Write-Host "Installed $($r.Path). Nothing was started; Night Atlas starts at your next logon. Logs: %LOCALAPPDATA%\NightAtlas\logs\autostart.log"
    }
}
