"""Local Chrome CDP BetKanyon prematch fetcher.

Attaches to the operator Chrome on 127.0.0.1:9222 (same process as
Kolay90), waits out Cloudflare on sport.bksp3.com, then relays
payloads through in-page fetch. Never uses ZenRows. Never closes Chrome.
"""

from __future__ import annotations

import os
import time

from parsers.betkanyon_prematch.cdp import (
    attach_sport_page,
    cdp_url,
    detach,
    looks_like_cloudflare_page,
)
from parsers.betkanyon_prematch.fetcher import (
    FETCH_BATCH_SIZE,
    PATHS,
    SPORT_PAGE,
    build_prematch_url,
    extract_encrypted_payload,
)

_BATCH_JS = """
async (urls) => {
    return Promise.all(urls.map(async (url) => {
        try {
            const response = await fetch(url, { credentials: "include" });
            const json = await response.json();
            return json.payload || json.Payload || null;
        } catch (e) {
            return null;
        }
    }));
}
"""

CLOUDFLARE_WAIT_SECONDS = float(os.getenv("BETKANYON_CF_WAIT_SECONDS", "180"))
CLOUDFLARE_POLL_SECONDS = 3.0


class BetkanyonPrematchCdpFetcher:
    def __init__(self, cdp_endpoint: str | None = None):
        self.cdp_endpoint = cdp_endpoint or cdp_url()
        self.playwright = None
        self.browser = None
        self.page = None
        self.context = None
        self.initialized = False
        self._working_path = PATHS[0]
        self.cloudflare_blocked = False

    def _connect(self):
        if self.initialized and self.page is not None:
            try:
                if not self.page.is_closed():
                    return
            except Exception:
                pass
        print(
            f"[BETKANYON PREMATCH] attaching local Chrome CDP {self.cdp_endpoint}"
        )
        attached = attach_sport_page(self.cdp_endpoint, sport_page=SPORT_PAGE)
        self.playwright = attached["playwright"]
        self.browser = attached["browser"]
        self.page = attached["page"]
        self.context = attached.get("context")
        if self.page is None:
            raise RuntimeError(
                "BetKanyon sport.bksp3.com tab missing on Chrome CDP "
                f"{self.cdp_endpoint}. Keep the operator Chrome open."
            )
        if attached.get("opened_tab"):
            print(f"[BETKANYON PREMATCH] opened {SPORT_PAGE} in existing Chrome")
        self._wait_for_cloudflare()
        self.initialized = True

    def _wait_for_cloudflare(self):
        deadline = time.monotonic() + CLOUDFLARE_WAIT_SECONDS
        announced = False
        while looks_like_cloudflare_page(self.page):
            self.cloudflare_blocked = True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(
                    "BetKanyon Chrome tab is still on a Cloudflare challenge. "
                    "Solve it in the open sport.bksp3.com window; do not close Chrome."
                )
            if not announced:
                print(
                    "[BETKANYON PREMATCH] Cloudflare challenge on sport.bksp3.com — "
                    f"solve it in the open Chrome tab ({int(CLOUDFLARE_WAIT_SECONDS)}s)"
                )
                announced = True
            time.sleep(min(CLOUDFLARE_POLL_SECONDS, remaining))
        if announced:
            print("[BETKANYON PREMATCH] Cloudflare cleared; relaying payloads via Chrome")
        self.cloudflare_blocked = False

    def _evaluate_urls(self, urls):
        if not self.initialized:
            self._connect()
        if looks_like_cloudflare_page(self.page):
            self._wait_for_cloudflare()
        return self.page.evaluate(_BATCH_JS, urls)

    def _try_cookie_http(self, tournament_ids):
        """If Chrome cookies satisfy Cloudflare, fall back to faster HTTP."""
        try:
            from parsers.betkanyon_prematch.fetcher import BetkanyonPrematchHttpFetcher

            cookies = []
            if self.context is not None:
                cookies = self.context.cookies()
            elif self.page is not None:
                cookies = self.page.context.cookies()
            if not cookies:
                return None
            http = BetkanyonPrematchHttpFetcher()
            for cookie in cookies:
                name = cookie.get("name")
                value = cookie.get("value")
                if not name:
                    continue
                http.session.cookies.set(
                    name,
                    value or "",
                    domain=cookie.get("domain") or None,
                    path=cookie.get("path") or "/",
                )
            probe_ids = list(tournament_ids[:1])
            payloads = http.fetch_all(probe_ids)
            if getattr(http, "cloudflare_blocked", False) or not payloads:
                http.close()
                return None
            print("[BETKANYON PREMATCH] Chrome cookies unlocked direct HTTP")
            return http
        except Exception as exc:
            print(
                f"[BETKANYON PREMATCH] cookie HTTP skipped "
                f"({type(exc).__name__}: {exc})"
            )
            return None

    def fetch_tournament(self, tournament_id):
        payloads = self.fetch_all([tournament_id])
        return payloads.get(str(tournament_id))

    def fetch_all(self, tournament_ids):
        self._connect()
        ids = [str(tid) for tid in tournament_ids]
        cookie_http = self._try_cookie_http(ids)
        if cookie_http is not None:
            try:
                return cookie_http.fetch_all(ids)
            finally:
                cookie_http.close()

        results = {}
        total = len(ids)
        paths_to_try = (
            self._working_path,
            *[p for p in PATHS if p != self._working_path],
        )
        for offset in range(0, total, FETCH_BATCH_SIZE):
            chunk = ids[offset : offset + FETCH_BATCH_SIZE]
            payloads = []
            for path in paths_to_try:
                urls = [build_prematch_url(tid, path=path) for tid in chunk]
                payloads = self._evaluate_urls(urls) or []
                if any(payloads):
                    self._working_path = path
                    break
            for tid, payload in zip(chunk, payloads or []):
                extracted = extract_encrypted_payload(payload, "")
                if extracted:
                    results[tid] = extracted
                elif isinstance(payload, str) and len(payload.strip()) > 20:
                    results[tid] = payload
            done = min(offset + FETCH_BATCH_SIZE, total)
            if done == total or done % 40 == 0 or offset == 0:
                print(
                    f"[BETKANYON PREMATCH] fetch progress: {done}/{total} "
                    f"(payloads={len(results)} via Chrome)"
                )
        return results

    def close(self):
        self.page = None
        self.context = None
        self.browser = None
        playwright = self.playwright
        self.playwright = None
        self.initialized = False
        detach(playwright)
