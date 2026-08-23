"""Persistent ZenRows browser for Kolay90 prematch.

Connects with ZENROWS_BROWSER_WS directly.

Does not use connect_with_failover or CredentialManager health writes.
Those share runtime/credentials_state.json with live BetKanyon/OnWin.
This experiment was blocked by a stale zenrows-env-legacy
QUOTA_EXHAUSTED cooldown even though the current env key accepts CDP.
"""

from __future__ import annotations

import os

from playwright.sync_api import sync_playwright

from credentials.zenrows_provider import apply_persistent_session_ttl


class Kolay90PrematchBrowser:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self._page = None
        self.credential_id = "kolay90-env-zenrows"

    def connect(self):
        if self.browser is not None:
            return
        browser_ws = (os.environ.get("ZENROWS_BROWSER_WS") or "").strip()
        if not browser_ws:
            raise RuntimeError("ZENROWS_BROWSER_WS is not set")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.connect_over_cdp(
            apply_persistent_session_ttl(browser_ws)
        )
        if self.browser.contexts:
            self.context = self.browser.contexts[0]
        else:
            self.context = self.browser.new_context()

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
