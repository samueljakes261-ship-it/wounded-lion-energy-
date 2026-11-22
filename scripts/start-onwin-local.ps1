# Start the Onwin live collector in the Chrome window Kolay91 already opened.
# Odds are sent outbound to the VPS. Chrome stays on this machine.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

Write-Host "Onwin local collector"
Write-Host "Repo: $Root"
& $Python -m parsers.onwin.local_collector
exit $LASTEXITCODE
