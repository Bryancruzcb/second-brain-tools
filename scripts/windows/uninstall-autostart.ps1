<#
.SYNOPSIS
    Remove the Night Atlas logon entry that install-autostart.ps1 created.

.DESCRIPTION
    Removes only the Startup shortcut 'NightAtlas-Autostart.lnk' and/or the
    scheduled task '\NightAtlas-Autostart', and only when they carry this
    project's marker. Every other scheduled task and shortcut is left alone.
    It does not stop a backend or frontend that is already running.

    -DryRun (or -WhatIf) shows what would be removed and changes nothing.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\uninstall-autostart.ps1
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet('All', 'StartupFolder', 'Task')][string]$Method = 'All',
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

function Get-NightAtlasShortcutDescription {
    param([string]$Path)
    $shell = New-Object -ComObject WScript.Shell
    return $shell.CreateShortcut($Path).Description
}

function Uninstall-NightAtlasAutostart {
    [CmdletBinding(SupportsShouldProcess = $true)]
    param([string]$Method, [string]$StartupDir, [bool]$DryRun)
    $removed = @()
    $prefix = ''
    if ($DryRun) { $prefix = 'DRY RUN: would remove ' } else { $prefix = 'Removing ' }

    if ($Method -in @('All', 'StartupFolder')) {
        $lnk = Join-Path (Get-NightAtlasStartupDir -StartupDir $StartupDir) ($script:NightAtlasEntryName + '.lnk')
        if (Test-Path -LiteralPath $lnk) {
            if ((Get-NightAtlasShortcutDescription -Path $lnk) -ne $script:NightAtlasMarker) {
                Write-Warning "$lnk was not created by install-autostart.ps1; leaving it."
            } else {
                Write-Host "$prefix$lnk"
                if (-not $DryRun -and $PSCmdlet.ShouldProcess($lnk, 'Remove startup shortcut')) {
                    Remove-Item -LiteralPath $lnk -Force
                    $removed += $lnk
                }
            }
        } else {
            Write-Host "No startup shortcut at $lnk."
        }
    }

    if ($Method -in @('All', 'Task')) {
        if (-not (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue)) {
            Write-Host 'Task Scheduler cmdlets unavailable; skipping task check.'
        } else {
            $task = Get-ScheduledTask -TaskName $script:NightAtlasEntryName -TaskPath '\' -ErrorAction SilentlyContinue
            if (-not $task) {
                Write-Host "No scheduled task \$($script:NightAtlasEntryName)."
            } elseif ($task.Description -ne $script:NightAtlasMarker) {
                Write-Warning "Task \$($script:NightAtlasEntryName) was not created by install-autostart.ps1; leaving it."
            } else {
                Write-Host "${prefix}task \$($script:NightAtlasEntryName)"
                if (-not $DryRun -and $PSCmdlet.ShouldProcess("\$($script:NightAtlasEntryName)", 'Unregister scheduled task')) {
                    Unregister-ScheduledTask -TaskName $script:NightAtlasEntryName -TaskPath '\' -Confirm:$false
                    $removed += "\$($script:NightAtlasEntryName)"
                }
            }
        }
    }
    return ,$removed
}

if ($MyInvocation.InvocationName -ne '.') {
    $r = Uninstall-NightAtlasAutostart -Method $Method -StartupDir $StartupDir -DryRun ([bool]$DryRun) -WhatIf:$WhatIfPreference
    if ($r.Count -gt 0) { Write-Host "Removed: $($r -join ', '). Running services were not stopped." }
}
