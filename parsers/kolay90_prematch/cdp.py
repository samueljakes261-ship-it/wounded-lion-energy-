"""Attach to an already-running local Chrome. Never launches or closes it."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

DEFAULT_CDP_URL = "http://127.0.0.1:9222"


def cdp_url() -> str:
    return (os.environ.get("KOLAY90_CDP_URL") or DEFAULT_CDP_URL).strip()


def connect_existing_chrome(url: str | None = None):
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    browser = playwright.chromium.connect_over_cdp(url or cdp_url())
    return playwright, browser


def list_pages(browser) -> list[dict]:
    rows = []
    for context in browser.contexts:
        for page in context.pages:
            title = ""
            try:
                title = page.title() or ""
            except Exception:
                title = ""
            rows.append(
                {
                    "url": (page.url or "").split("?")[0],
                    "title": title[:120],
                    "page": page,
                }
            )
    return rows


def find_kolay90_page(rows: list[dict]):
    for row in rows:
        host = (urlsplit(row.get("url") or "").hostname or "").lower()
        if host == "kolay90.com" or host.endswith(".kolay90.com"):
            return row
    return None


def attach_kolay90_page(url: str | None = None) -> dict:
    """Connect to the existing Chrome process and return its Kolay90 tab.

    Does not launch Chrome, create a profile, or close the browser.
    """
    playwright, browser = connect_existing_chrome(url)
    rows = list_pages(browser)
    found = find_kolay90_page(rows)
    return {
        "playwright": playwright,
        "browser": browser,
        "pages": [{"url": row["url"], "title": row["title"]} for row in rows],
        "page": None if found is None else found["page"],
        "url": None if found is None else found["url"],
        "title": None if found is None else found["title"],
    }


def detach(playwright) -> None:
    """Drop the CDP client only. Chrome stays running."""
    if playwright is None:
        return
    try:
        playwright.stop()
    except Exception:
        pass
