[CmdletBinding()]
param([switch]$BuildRunner, [string]$PythonPath)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Invoke-Checked {
    param([string]$Executable, [string[]]$CommandArgs)
    & $Executable @CommandArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed (exit $LASTEXITCODE): $Executable $($CommandArgs -join ' ')"
    }
}

Push-Location $projectRoot
try {
    $venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npmCommand) {
        throw 'Install Node.js 20.19+ or 22.12+ with npm and reopen PowerShell.'
    }
    if (-not (Test-Path -LiteralPath $venvPython)) {
        $launcherArgs = @()
        $basePython = $null
        if ($PythonPath) {
            $basePython = (Resolve-Path -LiteralPath $PythonPath).Path
        } else {
            $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
            if ($pythonCommand -and $pythonCommand.Source -notlike '*\WindowsApps\*') {
                $basePython = $pythonCommand.Source
            }
            if (-not $basePython) {
                $pythonCommand = Get-Command py.exe -ErrorAction SilentlyContinue
                if ($pythonCommand) {
                    $basePython = $pythonCommand.Source
                    $launcherArgs = @('-3')
                }
            }
            if (-not $basePython -and $env:LOCALAPPDATA) {
                $installRoot = Join-Path $env:LOCALAPPDATA 'Programs\Python'
                if (Test-Path -LiteralPath $installRoot) {
                    $installedPython = Get-ChildItem -LiteralPath $installRoot -Directory -Filter 'Python3*' |
                        ForEach-Object {
                            $versionMatch = [regex]::Match($_.Name, '^Python(\d)(\d{1,2})(?:[-_].*)?$')
                            $executable = Join-Path $_.FullName 'python.exe'
                            if ($versionMatch.Success -and (Test-Path -LiteralPath $executable)) {
                                $version = [version]("{0}.{1}" -f $versionMatch.Groups[1].Value, $versionMatch.Groups[2].Value)
                                if ($version -ge [version]'3.11') {
                                    [pscustomobject]@{ Version = $version; Executable = $executable }
                                }
                            }
                        } | Sort-Object Version -Descending | Select-Object -First 1
                    if ($installedPython) { $basePython = $installedPython.Executable }
                }
            }
        }
        if (-not $basePython) {
            throw 'Python 3.11+ was not found. Reuse an existing installation with -PythonPath C:\path\to\python.exe, or install Python.'
        }
        Invoke-Checked $basePython ($launcherArgs + @('-c', "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ is required'"))
        Invoke-Checked $basePython ($launcherArgs + @('-m', 'venv', '.venv'))
    }
    Invoke-Checked $venvPython @('-c', "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ is required'")
    Invoke-Checked $venvPython @('-m', 'pip', 'install', '-r', 'backend/requirements.txt')
    Push-Location (Join-Path $projectRoot 'frontend')
    try {
        if (Test-Path -LiteralPath 'package-lock.json') {
            Invoke-Checked $npmCommand.Source @('ci')
        } else {
            Invoke-Checked $npmCommand.Source @('install')
        }
    } finally {
        Pop-Location
    }
    $environmentFile = Join-Path $projectRoot '.env'
    if (-not (Test-Path -LiteralPath $environmentFile)) {
        Copy-Item -LiteralPath (Join-Path $projectRoot '.env.example') -Destination $environmentFile
        Write-Host 'Created .env from .env.example.'
    }
    if ($BuildRunner) {
        $dockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue
        if (-not $dockerCommand) {
            throw 'Docker Desktop is required to build the isolated runner. Install it and enable Linux containers.'
        }
        Invoke-Checked $dockerCommand.Source @('build', '-t', 'rootcause-runner:local', '-f', 'backend/runner/Dockerfile', 'backend/runner')
    }
    Write-Host 'Dependencies are ready. Start backend and frontend in separate terminals using scripts/start-backend.ps1 and scripts/start-frontend.ps1.'
} finally {
    Pop-Location
}
