Set-StrictMode -Version Latest

$script:ChatArchiverTaskName = 'Second Brain Chat Archiver'
$script:ChatArchiverTaskPath = '\'
$script:ChatArchiverStateDirectoryName = 'SecondBrain'

function Assert-WindowsHost {
    [CmdletBinding()]
    param()

    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw 'This script configures Windows Task Scheduler and must be run on Windows.'
    }
}

function Get-ChatArchiverStateDirectory {
    [CmdletBinding()]
    param()

    $localAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
    if ([string]::IsNullOrWhiteSpace($localAppData)) {
        if ([string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
            throw 'Could not determine the current user profile or LOCALAPPDATA directory.'
        }
        $localAppData = Join-Path $env:USERPROFILE 'AppData\Local'
    }

    return Join-Path $localAppData $script:ChatArchiverStateDirectoryName
}

function Get-ChatArchiverDefaultConfigPath {
    [CmdletBinding()]
    param()

    return Join-Path (Get-ChatArchiverStateDirectory) 'chat-archiver-task.json'
}

function Get-ChatArchiverDefaultStatusPath {
    [CmdletBinding()]
    param()

    return Join-Path (Get-ChatArchiverStateDirectory) 'chat-archiver-status.json'
}

function Resolve-ChatArchiverFile {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Description was not found: $Path"
    }

    return (Resolve-Path -LiteralPath $Path -ErrorAction Stop).ProviderPath
}

function Resolve-ChatArchiverOutputPath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }

    return [IO.Path]::GetFullPath((Join-Path (Get-Location).ProviderPath $Path))
}

function Resolve-ChatArchiverPython {
    [CmdletBinding()]
    param(
        [string]$PythonPath
    )

    $candidates = New-Object System.Collections.Generic.List[object]

    if (-not [string]::IsNullOrWhiteSpace($PythonPath)) {
        if (Test-Path -LiteralPath $PythonPath -PathType Leaf) {
            $item = Get-Item -LiteralPath $PythonPath -ErrorAction Stop
            $candidates.Add([pscustomobject]@{
                    Path = $item.FullName
                    IsLauncher = $item.Name -ieq 'py.exe'
                })
        }
        else {
            $command = Get-Command $PythonPath -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($null -eq $command) {
                throw "Python executable was not found: $PythonPath"
            }
            $candidates.Add([pscustomobject]@{
                    Path = $command.Source
                    IsLauncher = $command.Name -ieq 'py.exe'
                })
        }
    }
    else {
        foreach ($commandName in @('py.exe', 'python.exe', 'python3.exe')) {
            $command = Get-Command $commandName -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($null -ne $command) {
                $candidates.Add([pscustomobject]@{
                        Path = $command.Source
                        IsLauncher = $command.Name -ieq 'py.exe'
                    })
            }
        }
    }

    if ($candidates.Count -eq 0) {
        throw 'Python 3.10+ was not found. Install it, then retry with -PythonPath if it is not on PATH.'
    }

    $probeCode = 'import json, sys; print(json.dumps({"executable": sys.executable, "major": sys.version_info[0], "minor": sys.version_info[1]}))'
    foreach ($candidate in $candidates) {
        try {
            $launcherArguments = @()
            if ($candidate.IsLauncher) {
                $launcherArguments += '-3'
            }
            $launcherArguments += @('-c', $probeCode)

            $probeOutput = @(& $candidate.Path @launcherArguments 2>$null)
            if ($LASTEXITCODE -ne 0 -or $probeOutput.Count -eq 0) {
                continue
            }

            $probe = $probeOutput[-1] | ConvertFrom-Json -ErrorAction Stop
            if ([int]$probe.major -ne 3 -or [int]$probe.minor -lt 10) {
                continue
            }
            if (-not (Test-Path -LiteralPath ([string]$probe.executable) -PathType Leaf)) {
                continue
            }

            return (Resolve-Path -LiteralPath ([string]$probe.executable) -ErrorAction Stop).ProviderPath
        }
        catch {
            continue
        }
    }

    throw 'A working Python 3.10+ interpreter could not be resolved. Pass its full python.exe path with -PythonPath.'
}

function Get-OneDriveRoots {
    [CmdletBinding()]
    param()

    $roots = New-Object System.Collections.Generic.List[string]
    foreach ($environmentName in @('OneDriveConsumer', 'OneDriveCommercial', 'OneDrive')) {
        $value = [Environment]::GetEnvironmentVariable($environmentName, 'Process')
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            $roots.Add($value)
        }
    }

    if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        $accountsPath = 'HKCU:\Software\Microsoft\OneDrive\Accounts'
        if (Test-Path -LiteralPath $accountsPath) {
            foreach ($account in Get-ChildItem -LiteralPath $accountsPath -ErrorAction SilentlyContinue) {
                $accountProperties = Get-ItemProperty -LiteralPath $account.PSPath -Name UserFolder -ErrorAction SilentlyContinue
                $userFolder = $null
                if ($null -ne $accountProperties -and $null -ne $accountProperties.PSObject.Properties['UserFolder']) {
                    $userFolder = [string]$accountProperties.UserFolder
                }
                if (-not [string]::IsNullOrWhiteSpace($userFolder)) {
                    $roots.Add($userFolder)
                }
            }
        }
    }

    $uniqueRoots = @{}
    foreach ($root in $roots) {
        if (Test-Path -LiteralPath $root -PathType Container) {
            $resolved = (Resolve-Path -LiteralPath $root -ErrorAction Stop).ProviderPath
            $uniqueRoots[$resolved] = $resolved
        }
    }

    return @($uniqueRoots.Values)
}

function Resolve-OneDriveObsidianVault {
    [CmdletBinding()]
    param(
        [string]$VaultPath
    )

    if (-not [string]::IsNullOrWhiteSpace($VaultPath)) {
        if (-not (Test-Path -LiteralPath $VaultPath -PathType Container)) {
            throw "Vault directory was not found: $VaultPath"
        }

        $resolvedVault = (Resolve-Path -LiteralPath $VaultPath -ErrorAction Stop).ProviderPath
        if (-not (Test-Path -LiteralPath (Join-Path $resolvedVault '.obsidian') -PathType Container)) {
            Write-Warning "The selected directory does not contain a .obsidian folder: $resolvedVault"
        }
        return $resolvedVault
    }

    $oneDriveRoots = @(Get-OneDriveRoots)
    if ($oneDriveRoots.Count -eq 0) {
        throw 'No local OneDrive folder was detected. Pass the local Obsidian vault directory with -VaultPath.'
    }

    $candidateMap = @{}
    foreach ($root in $oneDriveRoots) {
        foreach ($relativePath in @(
                'Documents\Obsidian Vault',
                'Documents\Obsidian',
                'Obsidian Vault',
                'Obsidian'
            )) {
            $candidatePath = Join-Path $root $relativePath
            if (Test-Path -LiteralPath $candidatePath -PathType Container) {
                $resolved = (Resolve-Path -LiteralPath $candidatePath -ErrorAction Stop).ProviderPath
                $candidateMap[$resolved] = $resolved
            }
        }

        foreach ($parentPath in @($root, (Join-Path $root 'Documents'))) {
            if (-not (Test-Path -LiteralPath $parentPath -PathType Container)) {
                continue
            }

            foreach ($directory in Get-ChildItem -LiteralPath $parentPath -Directory -ErrorAction SilentlyContinue) {
                if (Test-Path -LiteralPath (Join-Path $directory.FullName '.obsidian') -PathType Container) {
                    $candidateMap[$directory.FullName] = $directory.FullName
                }
            }
        }
    }

    $candidates = @($candidateMap.Values | Sort-Object)
    if ($candidates.Count -eq 0) {
        throw 'No Obsidian vault was found in a local OneDrive folder. Pass the exact directory with -VaultPath.'
    }

    $markedCandidates = @($candidates | Where-Object {
            Test-Path -LiteralPath (Join-Path $_ '.obsidian') -PathType Container
        })
    if ($markedCandidates.Count -eq 1) {
        return $markedCandidates[0]
    }
    if ($candidates.Count -eq 1) {
        Write-Warning "The auto-detected directory does not contain a .obsidian folder: $($candidates[0])"
        return $candidates[0]
    }

    $formattedCandidates = ($candidates | ForEach-Object { "  - $_" }) -join [Environment]::NewLine
    throw "Multiple possible OneDrive Obsidian vaults were found. Rerun with -VaultPath and choose one:$([Environment]::NewLine)$formattedCandidates"
}

function ConvertTo-WindowsCommandLineArgument {
    [CmdletBinding()]
    param(
        [AllowEmptyString()]
        [Parameter(Mandatory = $true)]
        [string]$Value
    )

    # Follow CommandLineToArgvW escaping rules so spaces and trailing slashes remain intact.
    $builder = New-Object Text.StringBuilder
    [void]$builder.Append('"')
    $backslashCount = 0

    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq [char]92) {
            $backslashCount++
            continue
        }

        if ($character -eq [char]34) {
            [void]$builder.Append(('\' * (($backslashCount * 2) + 1)))
            [void]$builder.Append('"')
        }
        else {
            if ($backslashCount -gt 0) {
                [void]$builder.Append(('\' * $backslashCount))
            }
            [void]$builder.Append($character)
        }
        $backslashCount = 0
    }

    if ($backslashCount -gt 0) {
        [void]$builder.Append(('\' * ($backslashCount * 2)))
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Read-ChatArchiverConfig {
    [CmdletBinding()]
    param(
        [string]$Path = (Get-ChatArchiverDefaultConfigPath)
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }

    try {
        return Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        Write-Warning "Could not read installer state from '$Path': $($_.Exception.Message)"
        return $null
    }
}
