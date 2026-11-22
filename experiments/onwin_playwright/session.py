"""Headed local Chromium for the Onwin experiment.

The debugging port is not opened. The profile stays in this experiment
directory and is not read by the production collector.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "experiments" / "onwin_playwright" / "chrome_profile"
# Same live page the production feed opens. Override with ONWIN_EXPERIMENT_URL
# when Onwin has moved to another mirror. This module does not import the
# production browser.
DEFAULT_PAGE = "https://onwin4505.com/sportsbook/live/main-line/soccer"
MAIN_LINE = "get_main_line.erisgaming"
UPDATE_FRAGMENTS = (
    "find_event_snapshots.erisgaming",
    "get_main_line_gap.erisgaming",
)


def page_url() -> str:
    return (os.environ.get("ONWIN_EXPERIMENT_URL") or DEFAULT_PAGE).strip()


def prepare_profile() -> Path:
    PROFILE.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(PROFILE, 0o700)
    except OSError:
        pass
    return PROFILE


def launch_context():
    """Return (playwright, context). Chromium is headed unless ONWIN_EXPERIMENT_HEADLESS=1."""
    from playwright.sync_api import sync_playwright

    headless = (os.environ.get("ONWIN_EXPERIMENT_HEADLESS") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    channel = (os.environ.get("ONWIN_EXPERIMENT_CHANNEL") or "").strip() or None
    playwright = sync_playwright().start()
    kwargs = {
        "user_data_dir": str(prepare_profile()),
        "headless": headless,
        "viewport": {"width": 1400, "height": 900},
        "args": ["--disable-dev-shm-usage"],
    }
    if channel:
        kwargs["channel"] = channel
    context = playwright.chromium.launch_persistent_context(**kwargs)
    return playwright, context
