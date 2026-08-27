"""BetKanyon LIVE acquisition.

In-page fetch of getliveevents from the same sport.bksp3.com
RequestHelper tab used by prematch. Default is local Chrome CDP
(127.0.0.1:9222). The old frontend host betkanyon1617.com no longer
resolves.

  BETKANYON_LIVE_FETCH=auto|cdp   local Chrome (default)
  BETKANYON_LIVE_FETCH=zenrows    existing ZenRows browser path
"""

from __future__ import annotations

import os
import time

API = (
    "https://sport.bksp3.com/"
    "0587cccf-5a4f-430c-a2b4-b1b98af7e3ad"
    "/live/getliveevents"
    "?sportId=1"
    "&checkIsActiveAndBetStatus=false"
    "&stakeTypes=1"
    "&stakeTypes=702"
    "&stakeTypes=2"
    "&stakeTypes=3"
    "&stakeTypes=37"
    "&langId=2"
    "&partnerId=107"
    "&countryCode=KE"
)

LIVE_PAGE = (
    "https://sport.bksp3.com/"
    "0587cccf-5a4f-430c-a2b4-b1b98af7e3ad"
    "/Tools/RequestHelper"
)

_FETCH_JS = """
async (url) => {
    const response = await fetch(url, { credentials: "include" });
    const json = await response.json();
    return json.payload || json.Payload || null;
}
"""

_PROBE_JS = """
async (url) => {
    try {
        const response = await fetch(url, { credentials: "include" });
        const json = await response.json();
        const payload = json.payload || json.Payload || null;
        return typeof payload === "string" && payload.length > 20
            ? payload.length : 0;
    } catch (e) {
        return 0;
    }
}
"""

API_READY_WAIT_SECONDS = float(os.getenv("BETKANYON_LIVE_API_READY_SECONDS", "90"))
API_READY_POLL_SECONDS = 3.0


def _fetch_mode() -> str:
    return os.getenv("BETKANYON_LIVE_FETCH", "auto").strip().lower()


def _use_zenrows() -> bool:
    return _fetch_mode() in {"zenrows", "browser"}


class BetkanyonFetcher:

    def __init__(self):

        self.browser = None
        self.page = None
        self.initialized = False
        self._cdp_playwright = None
        self._use_cdp = not _use_zenrows()

    def _connect(self):

        print("\nConnecting browser...\n")

        if self._use_cdp:
            self._connect_cdp()
        else:
            self._connect_zenrows()

        self.initialized = True

    def _connect_cdp(self):
        from parsers.betkanyon_prematch.cdp import (
            attach_sport_page,
            looks_like_cloudflare_page,
        )

        print("[BETKANYON] attaching local Chrome CDP for live getliveevents")
        attached = attach_sport_page(sport_page=LIVE_PAGE)
        self._cdp_playwright = attached["playwright"]
        self.page = attached["page"]
        if self.page is None:
            raise RuntimeError(
                "BetKanyon sport.bksp3.com tab missing on Chrome CDP. "
                "Keep the operator Chrome open."
            )
        if attached.get("opened_tab"):
            print(f"[BETKANYON] opened {LIVE_PAGE} in existing Chrome")
        deadline = time.monotonic() + API_READY_WAIT_SECONDS
        announced = False
        while looks_like_cloudflare_page(self.page):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    "BetKanyon Chrome tab is still on a Cloudflare challenge. "
                    "Solve it in the open sport.bksp3.com window; do not close Chrome."
                )
            if not announced:
                print("[BETKANYON] Cloudflare challenge on sport.bksp3.com — waiting")
                announced = True
            time.sleep(min(API_READY_POLL_SECONDS, remaining))
        self._wait_for_api_ready()
        print("Browser ready.\n")

    def _wait_for_api_ready(self):
        deadline = time.monotonic() + API_READY_WAIT_SECONDS
        announced = False
        while time.monotonic() < deadline:
            try:
                n = int(self.page.evaluate(_PROBE_JS, API) or 0)
            except Exception:
                n = 0
            if n > 0:
                print(f"[BETKANYON] in-page live API ready (probe payload {n} bytes)")
                return
            remaining = deadline - time.monotonic()
            if not announced:
                print("[BETKANYON] waiting for getliveevents in-page fetch")
                announced = True
            time.sleep(min(API_READY_POLL_SECONDS, max(remaining, 0.5)))
        raise RuntimeError(
            "BetKanyon Chrome tab loaded but live API fetch is still challenged. "
            "Complete Cloudflare in the open sport.bksp3.com window; do not close Chrome."
        )

    def _connect_zenrows(self):
        from parsers.betkanyon.browser import BetkanyonBrowser

        self.browser = BetkanyonBrowser()
        self.browser.open()
        self.page = self.browser.page
        print("Opening live RequestHelper page...")
        self.browser.goto(LIVE_PAGE)
        self.browser.wait(5000)
        print("Browser ready.\n")

    def _wait(self, milliseconds):
        if self.browser is not None:
            self.browser.wait(milliseconds)
            return
        if self.page is not None:
            try:
                self.page.wait_for_timeout(milliseconds)
                return
            except Exception:
                pass
        time.sleep(milliseconds / 1000.0)

    def _reset_browser(self):

        print("\nBrowser connection lost. Reconnecting...\n")

        self.close()
        self._connect()

    def fetch(self):

        if not self.initialized:

            self._connect()

        for attempt in range(5):

            print(
                f"Fetching encrypted payload (attempt {attempt + 1}/5)..."
            )

            try:

                payload = self.page.evaluate(_FETCH_JS, API)

                if payload:

                    print(f"Payload length: {len(payload)}")

                    return payload

            except Exception as e:

                print(f"Fetch failed: {e}")

                message = str(e).lower()

                if (
                    "target page" in message
                    or "browser has been closed" in message
                    or "context has been closed" in message
                    or "socket hang up" in message
                    or "websocket" in message
                    or "connection closed" in message
                    or "epipe" in message
                ):

                    self._reset_browser()

                    continue

            self._wait(3000)

        raise TimeoutError(
            "Timed out waiting for BetKanyon payload."
        )

    def close(self):

        page = self.page
        self.page = None
        self.initialized = False
        if self._cdp_playwright is not None:
            from parsers.betkanyon_prematch.cdp import detach

            playwright = self._cdp_playwright
            self._cdp_playwright = None
            detach(playwright)
            return
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
            self.browser = None
        _ = page
