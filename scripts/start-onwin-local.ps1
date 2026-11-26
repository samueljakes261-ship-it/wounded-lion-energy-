# Onwin live and prematch odds are collected by the VPS Chrome on port 9223.
# This PC runs only the Kolay91 collector. Pass -Force to use the old
# Windows Onwin collector, which posts into the same snapshot files.
param([switch]$Force)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $Force) {
    Write-Host "Onwin runs on the VPS, not on this PC."
    Write-Host "Leave this machine on the Kolay91 collector only:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\start-kolay90-local.ps1"
    Write-Host "On the VPS:"
    Write-Host "  experiments/onwin_vps/chrome.sh status"
    Write-Host "  experiments/onwin_vps/collector.sh status"
    exit 0
}

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

Write-Host "Onwin local collector (forced)"
Write-Host "Repo: $Root"
& $Python -m parsers.onwin.local_collector
exit $LASTEXITCODE
