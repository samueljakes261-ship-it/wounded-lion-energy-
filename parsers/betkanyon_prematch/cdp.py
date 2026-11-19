"""Attach BetKanyon prematch to an already-running local Chrome.

Shares the operator Chrome on 127.0.0.1:9222 with Kolay90. Never
launches or closes that browser. Cloudflare must be solved in the
open sport.bksp3.com tab; in-page fetch then relays the payloads.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

DEFAULT_CDP_URL = "http://127.0.0.1:9222"
SPORT_HOST_MARKERS = ("sport.bksp3.com",)


def cdp_url() -> str:
    return (
        os.environ.get("BETKANYON_CDP_URL")
        or os.environ.get("KOLAY90_CDP_URL")
        or DEFAULT_CDP_URL
    ).strip()


def connect_existing_chrome(url: str | None = None):
    from engine.sync_playwright_thread import start_sync_playwright

    playwright = start_sync_playwright()
    browser = playwright.chromium.connect_over_cdp(url or cdp_url())
    return playwright, browser


def list_pages(browser) -> list[dict]:
    rows = []
    for context in browser.contexts:
        for page in context.pages:
            rows.append(
                {
                    "url": (page.url or "").split("?")[0],
                    "title": "",
                    "page": page,
                    "context": context,
                }
            )
    return rows


def find_sport_page(rows: list[dict]):
    for row in rows:
        host = (urlsplit(row.get("url") or "").hostname or "").lower()
        if any(host == marker or host.endswith("." + marker) for marker in SPORT_HOST_MARKERS):
            return row
        if "bksp3.com" in host:
            return row
    return None


def looks_like_cloudflare_page(page) -> bool:
    """True only for an interstitial challenge, not Cloudflare's jsd beacon.

    Passed pages still inject /cdn-cgi/challenge-platform/scripts/jsd/main.js.
    Treating that as a wall blocked BetKanyon payload relay for 180s.
    """
    try:
        title = (page.title() or "").lower()
    except Exception:
        title = ""
    if "just a moment" in title:
        return True
    try:
        content = (page.content() or "")[:2500].lower()
    except Exception:
        content = ""
    if "just a moment" in content:
        return True
    if "cf-browser-verification" in content:
        return True
    return False


def attach_sport_page(url: str | None = None, sport_page: str | None = None) -> dict:
    """Connect to existing Chrome and return the sport.bksp3.com tab.

    Opens SPORT_PAGE in a new tab if none exists. Does not close Chrome.
    """
    from parsers.betkanyon_prematch.fetcher import SPORT_PAGE

    playwright, browser = connect_existing_chrome(url)
    rows = list_pages(browser)
    found = find_sport_page(rows)
    opened = False
    if found is None:
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.new_page()
        target = sport_page or SPORT_PAGE
        page.goto(target, wait_until="domcontentloaded", timeout=120000)
        opened = True
        found = {
            "url": (page.url or "").split("?")[0],
            "title": "",
            "page": page,
            "context": context,
        }
        rows = list_pages(browser)
    return {
        "playwright": playwright,
        "browser": browser,
        "pages": [{"url": row["url"], "title": row["title"]} for row in rows],
        "page": None if found is None else found["page"],
        "context": None if found is None else found.get("context"),
        "url": None if found is None else found.get("url"),
        "opened_tab": opened,
        "cloudflare": bool(found and looks_like_cloudflare_page(found["page"])),
    }


def detach(playwright) -> None:
    """Drop the CDP client only. Chrome stays running."""
    if playwright is None:
        return
    try:
        playwright.stop()
    except Exception:
        pass
