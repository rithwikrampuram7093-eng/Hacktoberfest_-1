$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCommand) { throw 'npm.cmd was not found. Install Node.js and reopen PowerShell.' }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot 'frontend\node_modules'))) {
    throw 'Run .\scripts\setup.ps1 from the repository root first.'
}
Push-Location (Join-Path $projectRoot 'frontend')
try {
    & $npmCommand.Source run dev -- --host 127.0.0.1 --port 5173
    if ($LASTEXITCODE -ne 0) { throw "Frontend exited with code $LASTEXITCODE." }
} finally {
    Pop-Location
}
