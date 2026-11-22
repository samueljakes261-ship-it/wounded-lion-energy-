"""Attach the Onwin experiment to the Chrome window Kolay91 already uses.

That Chrome listens on 127.0.0.1:9222. This module opens one more tab in
it. It does not launch a second browser and it does not close Chrome.
"""

from __future__ import annotations

import os

DEFAULT_CDP = "http://127.0.0.1:9222"
DEFAULT_PAGE = "https://onwin4505.com/sportsbook/live/main-line/soccer"
MAIN_LINE = "get_main_line.erisgaming"
UPDATE_FRAGMENTS = (
    "find_event_snapshots.erisgaming",
    "get_main_line_gap.erisgaming",
)


def page_url() -> str:
    return (os.environ.get("ONWIN_EXPERIMENT_URL") or DEFAULT_PAGE).strip()


def cdp_url() -> str:
    return (os.environ.get("ONWIN_EXPERIMENT_CDP") or DEFAULT_CDP).strip()


def attach_existing_chrome():
    """Return (playwright, context, page) for a new tab in the Kolay Chrome."""
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(cdp_url())
        if not browser.contexts:
            raise RuntimeError("attached Chrome has no window")
        context = browser.contexts[0]
        page = context.new_page()
    except Exception:
        playwright.stop()
        raise
    return playwright, context, page


def release(playwright, page) -> None:
    """Close the Onwin tab and drop the debugger. Chrome keeps running."""
    if page is not None:
        try:
            page.close()
        except Exception:
            pass
    if playwright is not None:
        try:
            playwright.stop()
        except Exception:
            pass
