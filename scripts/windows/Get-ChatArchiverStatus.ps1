[CmdletBinding()]
param(
    [string]$TaskName = 'Second Brain Chat Archiver',
    [string]$TaskPath = '\',
    [string]$StatusFile,
    [string]$ConfigFile,
    [switch]$AsJson
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'ChatArchiver.Common.ps1')

Assert-WindowsHost
Import-Module ScheduledTasks -ErrorAction Stop

if ([string]::IsNullOrWhiteSpace($ConfigFile)) {
    $ConfigFile = Get-ChatArchiverDefaultConfigPath
}
$config = Read-ChatArchiverConfig -Path $ConfigFile

if ([string]::IsNullOrWhiteSpace($StatusFile)) {
    if ($null -ne $config -and $null -ne $config.PSObject.Properties['status_file']) {
        $StatusFile = [string]$config.status_file
    }
    else {
        $StatusFile = Get-ChatArchiverDefaultStatusPath
    }
}
$StatusFile = Resolve-ChatArchiverOutputPath -Path $StatusFile

$task = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue
$taskInfo = $null
if ($null -ne $task) {
    $taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath $TaskPath -ErrorAction Stop
}

$collectorStatus = $null
$statusParseError = $null
$statusFileItem = $null
if (Test-Path -LiteralPath $StatusFile -PathType Leaf) {
    $statusFileItem = Get-Item -LiteralPath $StatusFile -ErrorAction Stop
    try {
        $collectorStatus = Get-Content -LiteralPath $StatusFile -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        $statusParseError = $_.Exception.Message
    }
}

$collectorSuccess = $null
$collectorFinishedAt = $null
$collectorArchiveCount = $null
$collectorWarningCount = $null
$collectorError = $null
if ($null -ne $collectorStatus) {
    if ($null -ne $collectorStatus.PSObject.Properties['success']) {
        $collectorSuccess = [bool]$collectorStatus.success
    }
    if ($null -ne $collectorStatus.PSObject.Properties['finished_at']) {
        $collectorFinishedAt = [string]$collectorStatus.finished_at
    }
    if ($null -ne $collectorStatus.PSObject.Properties['archives']) {
        $collectorArchiveCount = @($collectorStatus.archives).Count
    }
    if ($null -ne $collectorStatus.PSObject.Properties['warnings']) {
        $collectorWarningCount = @($collectorStatus.warnings).Count
    }
    if ($null -ne $collectorStatus.PSObject.Properties['error']) {
        $collectorError = [string]$collectorStatus.error
    }
}

$lastResult = $null
$lastResultHex = $null
$lastResultMeaning = $null
if ($null -ne $taskInfo) {
    $lastResult = [int64]$taskInfo.LastTaskResult
    $lastResultHex = '0x{0:X8}' -f ([uint32]$taskInfo.LastTaskResult)
    switch ([uint32]$taskInfo.LastTaskResult) {
        0x00000000 { $lastResultMeaning = 'Success'; break }
        0x00041300 { $lastResultMeaning = 'Task is ready'; break }
        0x00041301 { $lastResultMeaning = 'Task is currently running'; break }
        0x00041302 { $lastResultMeaning = 'Task is disabled'; break }
        0x00041303 { $lastResultMeaning = 'Task has not yet run'; break }
        0x00041306 { $lastResultMeaning = 'Task was terminated'; break }
        default    { $lastResultMeaning = 'See the Task Scheduler operational log for details' }
    }
}

$summary = [ordered]@{
    TaskName            = $TaskName
    TaskPath            = $TaskPath
    Installed           = ($null -ne $task)
    Enabled             = if ($null -ne $task) { [bool]$task.Settings.Enabled } else { $null }
    State               = if ($null -ne $task) { [string]$task.State } else { 'NotInstalled' }
    LastRunTime         = if ($null -ne $taskInfo) { $taskInfo.LastRunTime } else { $null }
    NextRunTime         = if ($null -ne $taskInfo) { $taskInfo.NextRunTime } else { $null }
    LastTaskResult      = $lastResult
    LastTaskResultHex   = $lastResultHex
    LastResultMeaning   = $lastResultMeaning
    StatusFile          = $StatusFile
    StatusFileExists    = ($null -ne $statusFileItem)
    StatusFileUpdatedAt = if ($null -ne $statusFileItem) { $statusFileItem.LastWriteTime } else { $null }
    StatusParseError    = $statusParseError
    CollectorSuccess    = $collectorSuccess
    CollectorFinishedAt = $collectorFinishedAt
    ArchivesWritten     = $collectorArchiveCount
    CollectorWarnings   = $collectorWarningCount
    CollectorError      = $collectorError
}

$report = [ordered]@{
    summary          = [pscustomobject]$summary
    installer_config = $config
    collector_status = $collectorStatus
}

if ($AsJson) {
    [pscustomobject]$report | ConvertTo-Json -Depth 10
}
else {
    [pscustomobject]$summary | Format-List
    if ($null -ne $collectorStatus) {
        Write-Host 'Collector status payload:'
        $collectorStatus | ConvertTo-Json -Depth 10
    }
}

if ($null -eq $task) {
    exit 1
}
