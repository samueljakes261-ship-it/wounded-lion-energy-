"""BetKanyon LIVE acquisition.

Default is a direct HTTP pull of getliveevents. No ZenRows session is
opened. Set BETKANYON_LIVE_FETCH=cdp to attach to the operator's Chrome
on 127.0.0.1:9222 and fetch in-page instead.
"""

from __future__ import annotations

import os
import time

import requests

from parsers.betkanyon_prematch.fetcher import extract_encrypted_payload


LIVE_PAGE = (
    "https://sport.bksp3.com/"
    "0587cccf-5a4f-430c-a2b4-b1b98af7e3ad"
    "/Tools/RequestHelper"
)
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
REQUEST_TIMEOUT = 30
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "https://sport.bksp3.com",
    "Referer": LIVE_PAGE,
}

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
    return os.getenv("BETKANYON_LIVE_FETCH", "http").strip().lower()


class EmptyAcquisitionError(RuntimeError):
    """HTTP completed but no usable encrypted payload was returned."""


class BetkanyonFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.initialized = False
        self.page = None
        self.browser = None
        self._cdp_playwright = None
        self._use_cdp = _fetch_mode() in {"cdp", "auto"}
        self.last_meta = {
            "http_status": None,
            "content_type": None,
            "payload_bytes": 0,
        }

    def _connect(self):
        if self.initialized:
            return
        if self._use_cdp:
            self._connect_cdp()
        else:
            print("[BETKANYON] direct HTTP session started (no ZenRows)")
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
        self._connect()
        if self._use_cdp:
            return self._fetch_in_page()
        return self._fetch_http()

    def _fetch_http(self):
        last_error = None
        for attempt in range(5):
            try:
                response = self.session.get(API, timeout=REQUEST_TIMEOUT)
            except Exception as exc:
                last_error = exc
                print(
                    f"[BETKANYON] fetch failed ({type(exc).__name__}: {exc}) "
                    f"attempt {attempt + 1}/5"
                )
                time.sleep(1)
                continue

            content_type = response.headers.get("Content-Type", "")
            payload_bytes = len(response.content or b"")
            self.last_meta = {
                "http_status": response.status_code,
                "content_type": content_type,
                "payload_bytes": payload_bytes,
            }
            if response.status_code >= 400:
                last_error = RuntimeError(f"HTTP {response.status_code}")
                print(
                    f"[BETKANYON] fetch HTTP {response.status_code} "
                    f"content_type={content_type} payload_bytes={payload_bytes} "
                    f"attempt {attempt + 1}/5"
                )
                time.sleep(1)
                continue

            body = None
            try:
                body = response.json()
            except Exception:
                body = None
            payload = extract_encrypted_payload(body, response.text)
            if payload:
                return payload
            raise EmptyAcquisitionError(
                f"empty payload HTTP {response.status_code} "
                f"content_type={content_type} payload_bytes={payload_bytes}"
            )

        if last_error is not None:
            raise last_error
        raise EmptyAcquisitionError("empty payload after retries")

    def _fetch_in_page(self):
        for _attempt in range(5):
            try:
                payload = self.page.evaluate(_FETCH_JS, API)
                if payload:
                    self.last_meta = {
                        "http_status": 200,
                        "content_type": "application/json",
                        "payload_bytes": len(payload),
                    }
                    print(f"Payload length: {len(payload)}")
                    return payload
            except Exception as exc:
                print(f"Fetch failed: {exc}")
                message = str(exc).lower()
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
        raise TimeoutError("Timed out waiting for BetKanyon payload.")

    def close(self):
        page = self.page
        self.page = None
        self.initialized = False
        try:
            self.session.close()
        except Exception:
            pass
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
