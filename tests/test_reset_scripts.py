"""
Smoke tests for the restart/reset scripts, run in --dry-run/-DryRun
mode only (never stops/starts real processes or deletes real files).

Skips gracefully in environments missing the relevant shell.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _find_powershell():
    for candidate in ("powershell", "pwsh"):
        path = shutil.which(candidate)
        if path:
            return path
    return None


def _find_bash():
    explicit = Path(r"C:\Program Files\Git\bin\bash.exe")
    if explicit.exists():
        return str(explicit)
    return shutil.which("bash")


def test_reset_dev_dry_run_reports_planned_actions():
    powershell = _find_powershell()
    if not powershell:
        pytest.skip("PowerShell not available in this environment.")

    script = PROJECT_ROOT / "scripts" / "reset-dev.ps1"

    result = subprocess.run(
        [powershell, "-NoProfile", "-File", str(script), "-DryRun"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "DRY RUN" in result.stdout
    assert "Would start" in result.stdout
    assert "Dry run complete" in result.stdout


def test_reset_prod_dry_run_reports_planned_actions():
    bash = _find_bash()
    if not bash:
        pytest.skip("bash not available in this environment.")

    script = PROJECT_ROOT / "scripts" / "reset-prod.sh"

    result = subprocess.run(
        [bash, str(script), "--dry-run"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert "DRY RUN" in result.stdout
    assert "Dry run complete" in result.stdout


def test_reset_prod_rejects_unknown_argument():
    bash = _find_bash()
    if not bash:
        pytest.skip("bash not available in this environment.")

    script = PROJECT_ROOT / "scripts" / "reset-prod.sh"

    result = subprocess.run(
        [bash, str(script), "--not-a-real-flag"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
