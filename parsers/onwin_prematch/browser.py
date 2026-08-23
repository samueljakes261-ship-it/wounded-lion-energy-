"""Dedicated ZenRows browser for OnWin prematch.

Connects with ZENROWS_BROWSER_WS from .env directly. Does not use
connect_with_failover or CredentialManager, so leftover cooldowns in
runtime/credentials_state.json cannot block this worker.

Does not modify parsers.onwin.browser or utils.zenrows_persistent.
Never logs the websocket URL (it embeds the API key).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from credentials.zenrows_provider import apply_persistent_session_ttl

ROOT = Path(__file__).resolve().parents[2]


class OnwinPrematchBrowser:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self._page = None

    def connect(self):
        if self.browser is not None:
            return
        load_dotenv(ROOT / ".env", override=True)
        browser_ws = (os.environ.get("ZENROWS_BROWSER_WS") or "").strip()
        if not browser_ws:
            raise RuntimeError("ZENROWS_BROWSER_WS is not set")
        print(
            "[ONWIN PREMATCH] connecting via ZENROWS_BROWSER_WS "
            "(.env, no credential cooldown)"
        )
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(
            apply_persistent_session_ttl(browser_ws)
        )
        if self.browser.contexts:
            self.context = self.browser.contexts[0]
        else:
            self.context = self.browser.new_context()
        print("[ONWIN PREMATCH] ZenRows connected")

    def page(self):
        self.connect()
        if self._page is not None and not self._page.is_closed():
            return self._page
        self._page = self.context.new_page()
        return self._page

    def get_page(self):
        return self.page()

    def close(self):
        if self._page is not None:
            try:
                if not self._page.is_closed():
                    self._page.close()
            except Exception:
                pass
        if self.browser is not None:
            try:
                self.browser.close()
            except Exception:
                pass
        if self.playwright is not None:
            try:
                self.playwright.stop()
            except Exception:
                pass
        self._page = None
        self.context = None
        self.browser = None
        self.playwright = None
