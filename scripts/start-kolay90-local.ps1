# Start the Kolay90 prematch collector on this Windows PC.
# Chrome stays on this machine. Odds are sent outbound to the VPS.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

Write-Host "Kolay90 local collector"
Write-Host "Repo: $Root"
& $Python -m parsers.kolay90_prematch.local_collector
exit $LASTEXITCODE
