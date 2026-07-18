[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [string]$TaskName = 'Second Brain Chat Archiver',
    [string]$TaskPath = '\',
    [string]$StatusFile,
    [string]$ConfigFile,
    [switch]$RemoveState
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'ChatArchiver.Common.ps1')

Assert-WindowsHost
Import-Module ScheduledTasks -ErrorAction Stop

if ([string]::IsNullOrWhiteSpace($ConfigFile)) {
    $ConfigFile = Get-ChatArchiverDefaultConfigPath
}
$config = Read-ChatArchiverConfig -Path $ConfigFile

$task = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "Scheduled task '$TaskName' is not installed."
}
elseif ($PSCmdlet.ShouldProcess("Task Scheduler task '$TaskName'", 'Unregister')) {
    Unregister-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
}

if ($RemoveState) {
    if ([string]::IsNullOrWhiteSpace($StatusFile)) {
        if ($null -ne $config -and $null -ne $config.PSObject.Properties['status_file']) {
            $StatusFile = [string]$config.status_file
        }
        else {
            $StatusFile = Get-ChatArchiverDefaultStatusPath
        }
    }

    foreach ($stateFile in @($ConfigFile, $StatusFile) | Select-Object -Unique) {
        if (Test-Path -LiteralPath $stateFile -PathType Leaf) {
            if ($PSCmdlet.ShouldProcess($stateFile, 'Delete installer/status state file')) {
                Remove-Item -LiteralPath $stateFile -Force
            }
        }
    }
}
else {
    Write-Host 'Installer and run-status files were preserved. Use -RemoveState to delete them.'
}

Write-Host 'No archived notes were removed from the Obsidian vault.'
