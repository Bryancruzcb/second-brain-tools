[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [string]$VaultPath,
    [string]$PythonPath,
    [string]$CollectorPath,
    [string]$StatusFile,

    [ValidatePattern('^(?:[01]\d|2[0-3]):[0-5]\d$')]
    [string]$DailyTime = '23:00',

    [ValidateRange(1, 31)]
    [int]$LookbackDays = 2,

    [switch]$AtLogon,
    [switch]$WakeToRun,
    [switch]$RunNow,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'ChatArchiver.Common.ps1')

Assert-WindowsHost
Import-Module ScheduledTasks -ErrorAction Stop

if ([string]::IsNullOrWhiteSpace($CollectorPath)) {
    $CollectorPath = Join-Path (Split-Path -Parent $PSScriptRoot) 'chat_archiver.py'
}
if ([string]::IsNullOrWhiteSpace($StatusFile)) {
    $StatusFile = Get-ChatArchiverDefaultStatusPath
}

$resolvedCollector = Resolve-ChatArchiverFile -Path $CollectorPath -Description 'Chat collector'
$resolvedPython = Resolve-ChatArchiverPython -PythonPath $PythonPath
$resolvedVault = Resolve-OneDriveObsidianVault -VaultPath $VaultPath
$resolvedStatusFile = Resolve-ChatArchiverOutputPath -Path $StatusFile

$existingTask = Get-ScheduledTask `
    -TaskName $script:ChatArchiverTaskName `
    -TaskPath $script:ChatArchiverTaskPath `
    -ErrorAction SilentlyContinue
if ($null -ne $existingTask -and -not $Force) {
    throw "The scheduled task '$script:ChatArchiverTaskName' already exists. Use -Force to replace its definition."
}

$collectorArgument = ConvertTo-WindowsCommandLineArgument -Value $resolvedCollector
$vaultArgument = ConvertTo-WindowsCommandLineArgument -Value $resolvedVault
$statusArgument = ConvertTo-WindowsCommandLineArgument -Value $resolvedStatusFile
$actionArguments = "$collectorArgument --vault $vaultArgument --status-file $statusArgument --lookback-days $LookbackDays"

$action = New-ScheduledTaskAction `
    -Execute $resolvedPython `
    -Argument $actionArguments `
    -WorkingDirectory (Split-Path -Parent $resolvedCollector)

$runAt = [datetime]::ParseExact($DailyTime, 'HH:mm', [Globalization.CultureInfo]::InvariantCulture)
$triggers = @(
    New-ScheduledTaskTrigger -Daily -At $runAt
)
if ($AtLogon) {
    $currentUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $triggers += New-ScheduledTaskTrigger -AtLogOn -User $currentUser
}

$settingsParameters = @{
    StartWhenAvailable          = $true
    AllowStartIfOnBatteries     = $true
    DontStopIfGoingOnBatteries  = $true
    ExecutionTimeLimit          = (New-TimeSpan -Hours 2)
    MultipleInstances           = 'IgnoreNew'
}
if ($WakeToRun) {
    $settingsParameters['WakeToRun'] = $true
}
$settings = New-ScheduledTaskSettingsSet @settingsParameters

$currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal `
    -UserId $currentIdentity `
    -LogonType Interactive `
    -RunLevel Limited

$definition = New-ScheduledTask `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description 'Archives supported local AI chat sources into the OneDrive-synced Obsidian vault.'

$taskTarget = "Task Scheduler task '$script:ChatArchiverTaskName'"
if ($PSCmdlet.ShouldProcess($taskTarget, 'Register or replace')) {
    $stateDirectory = Get-ChatArchiverStateDirectory
    $statusDirectory = Split-Path -Parent $resolvedStatusFile
    foreach ($directory in @($stateDirectory, $statusDirectory) | Select-Object -Unique) {
        if (-not (Test-Path -LiteralPath $directory -PathType Container)) {
            New-Item -ItemType Directory -Path $directory -Force | Out-Null
        }
    }

    Register-ScheduledTask `
        -TaskName $script:ChatArchiverTaskName `
        -TaskPath $script:ChatArchiverTaskPath `
        -InputObject $definition `
        -Force:$Force | Out-Null

    $configPath = Get-ChatArchiverDefaultConfigPath
    $config = [ordered]@{
        schema_version  = 1
        task_name       = $script:ChatArchiverTaskName
        task_path       = $script:ChatArchiverTaskPath
        installed_at    = [datetime]::UtcNow.ToString('o')
        windows_user    = $currentIdentity
        python_path     = $resolvedPython
        collector_path  = $resolvedCollector
        vault_path      = $resolvedVault
        status_file     = $resolvedStatusFile
        daily_time      = $DailyTime
        lookback_days   = $LookbackDays
        at_logon        = [bool]$AtLogon
        wake_to_run     = [bool]$WakeToRun
        logon_type      = 'Interactive'
    }
    $config | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $configPath -Encoding UTF8

    if ($RunNow -and $PSCmdlet.ShouldProcess($taskTarget, 'Start now')) {
        Start-ScheduledTask -TaskName $script:ChatArchiverTaskName -TaskPath $script:ChatArchiverTaskPath
    }
}

[pscustomobject]@{
    TaskName      = $script:ChatArchiverTaskName
    DailyTime     = $DailyTime
    LookbackDays   = $LookbackDays
    AtLogon       = [bool]$AtLogon
    WakeToRun     = [bool]$WakeToRun
    Python        = $resolvedPython
    Collector     = $resolvedCollector
    Vault         = $resolvedVault
    StatusFile    = $resolvedStatusFile
    WhatIf        = [bool]$WhatIfPreference
}
