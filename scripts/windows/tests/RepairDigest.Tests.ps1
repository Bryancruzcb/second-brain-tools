# Pester 5+ tests for run-repair-digest.ps1. The backend probe and the Python
# call are mocked, so nothing is started and no real digest runs.

BeforeAll {
    . (Join-Path (Split-Path -Parent $PSScriptRoot) 'run-repair-digest.ps1')
    function script:New-FakeCheckout {
        $root = Join-Path ([System.IO.Path]::GetTempPath()) ('night atlas digest ' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path (Join-Path $root 'backend/venv/Scripts'), (Join-Path $root 'scripts') | Out-Null
        Set-Content -LiteralPath (Join-Path $root 'backend/venv/Scripts/python.exe') -Value ''
        Set-Content -LiteralPath (Join-Path $root 'scripts/repair_digest.py') -Value ''
        return $root
    }
}

Describe 'run-repair-digest.ps1' {
    BeforeEach {
        $script:Root = New-FakeCheckout
        $script:Out = Join-Path $script:Root 'out'
        $script:Logs = Join-Path $script:Root 'logs'
        $script:Now = [datetime]'2026-10-11T09:17:00'
        Mock Invoke-RepairDigestPython { @{ Code = 0; Output = @('ok') } }
    }
    AfterEach { Remove-Item -LiteralPath $script:Root -Recurse -Force -ErrorAction SilentlyContinue }

    It 'parses with no errors' {
        $errors = $null
        [System.Management.Automation.Language.Parser]::ParseFile((Join-Path (Split-Path -Parent $PSScriptRoot) 'run-repair-digest.ps1'), [ref]$null, [ref]$errors) | Out-Null
        $errors | Should -BeNullOrEmpty
    }

    It 'logs and exits 0 without running anything when the backend is down' {
        Mock Test-RepairDigestBackend { $false }
        Invoke-RepairDigest -RepoRoot $script:Root -ApiUrl 'http://127.0.0.1:1' -OutDir $script:Out -LogDir $script:Logs -Now $script:Now | Should -Be 0
        Should -Invoke Invoke-RepairDigestPython -Times 0 -Exactly
        Get-Content -Raw (Join-Path $script:Logs 'repair-digest.log') | Should -Match 'Nothing was started'
        Test-Path -LiteralPath $script:Out | Should -BeFalse
    }

    It 'first run: dated .md, latest.json, API only, no --previous' {
        Mock Test-RepairDigestBackend { $true }
        Invoke-RepairDigest -RepoRoot $script:Root -ApiUrl 'http://127.0.0.1:8000' -OutDir $script:Out -LogDir $script:Logs -Now $script:Now | Should -Be 0
        Should -Invoke Invoke-RepairDigestPython -Times 1 -Exactly -ParameterFilter {
            $a = $Arguments -join ' '
            $Python -like '*venv*python.exe' -and
            $a -like '*repair_digest.py --source api --url http://127.0.0.1:8000 --out *repair-digest-2026-10-11.md --json-out *repair-digest-latest.json' -and
            $a -notlike '*--previous*'
        }
    }

    It 'later runs diff against latest.json' {
        Mock Test-RepairDigestBackend { $true }
        New-Item -ItemType Directory -Force -Path $script:Out | Out-Null
        Set-Content -LiteralPath (Join-Path $script:Out 'repair-digest-latest.json') -Value '{}'
        Invoke-RepairDigest -RepoRoot $script:Root -ApiUrl 'http://127.0.0.1:8000' -OutDir $script:Out -LogDir $script:Logs -Now $script:Now | Should -Be 0
        Should -Invoke Invoke-RepairDigestPython -Times 1 -Exactly -ParameterFilter {
            ($Arguments -join ' ') -like '*--json-out *repair-digest-latest.json --previous *repair-digest-latest.json'
        }
    }

    It 'returns the digest exit code and logs its output' {
        Mock Test-RepairDigestBackend { $true }
        Mock Invoke-RepairDigestPython { @{ Code = 2; Output = @('repair_digest: boom') } }
        Invoke-RepairDigest -RepoRoot $script:Root -ApiUrl 'http://127.0.0.1:8000' -OutDir $script:Out -LogDir $script:Logs -Now $script:Now | Should -Be 2
        Get-Content -Raw (Join-Path $script:Logs 'repair-digest.log') | Should -Match 'boom'
    }

    It 'fails cleanly when the venv is missing' {
        Mock Test-RepairDigestBackend { $true }
        Remove-Item -LiteralPath (Join-Path $script:Root 'backend/venv') -Recurse -Force
        Invoke-RepairDigest -RepoRoot $script:Root -ApiUrl 'http://127.0.0.1:8000' -OutDir $script:Out -LogDir $script:Logs -Now $script:Now | Should -Be 1
        Should -Invoke Invoke-RepairDigestPython -Times 0 -Exactly
    }

    It 'a native command writing to stderr does not abort the wrapper' -Skip:($env:OS -ne 'Windows_NT') {
        $ErrorActionPreference = 'Stop'   # what the wrapper effectively runs under in Windows PowerShell
        $r = Invoke-RepairDigestPython -Python 'cmd.exe' -Arguments @('/c', 'echo out & echo err 1>&2 & exit 3')
        $r.Code | Should -Be 3
        ($r.Output -join ' ') | Should -Match 'err'
    }
}
