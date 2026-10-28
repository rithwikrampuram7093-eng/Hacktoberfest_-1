param([switch]$EnableTrustedDemoRunner)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    throw 'Run .\scripts\setup.ps1 from the repository root first.'
}
Push-Location $projectRoot
try {
    if ($EnableTrustedDemoRunner) {
        $env:RC_ENABLE_TRUSTED_DEMO_RUNNER = 'true'
        Write-Host 'Trusted local demo runner enabled for the three bundled scenarios only. Live/imported projects still require Docker.'
    }
    & $venvPython -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
    if ($LASTEXITCODE -ne 0) { throw "Backend exited with code $LASTEXITCODE." }
} finally {
    Pop-Location
}
