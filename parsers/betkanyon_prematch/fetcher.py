"""BetKanyon prematch acquisition.

Default (auto): try direct HTTP first. sport.bksp3.com is Cloudflare
protected, so a 403 challenge used to silently yield zero payloads and
BetKanyon never relayed data. Auto then attaches to the operator
Chrome on 127.0.0.1:9222 (same process as Kolay90) and in-page fetch
relays the encrypted payloads through.

Fallback env:
  BETKANYON_PREMATCH_FETCH=http      HTTP only
  BETKANYON_PREMATCH_FETCH=cdp       local Chrome only
  BETKANYON_PREMATCH_FETCH=zenrows   Playwright/ZenRows (fetcher_zenrows.py)

Live parsers.betkanyon.browser is not imported on the default path.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

SPORT_ORIGIN = "https://sport.bksp3.com"
SPORT_HOST = "https://sport.bksp3.com/0587cccf-5a4f-430c-a2b4-b1b98af7e3ad"
# Same-origin RequestHelper. The old frontend host betkanyon1617.com no
# longer resolves; in-page fetch from this page still hits the API.
SPORT_PAGE = SPORT_HOST + "/Tools/RequestHelper"
PREMATCH_PAGE = SPORT_PAGE
STAKE_TYPES = [1, 702, 37, 3, 2533, 313639, 2, 2532, 313638]
PATHS = (
    "/common/getmixedsportandeventslistwithoutright",
    "/prematch/getmixedsportsandeventswithoutright",
)
FETCH_BATCH_SIZE = 8
REQUEST_TIMEOUT = 30
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": SPORT_ORIGIN,
    "Referer": SPORT_PAGE,
}


def _date_window():
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=14)
    return (
        start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        end.strftime("%Y-%m-%dT23:59:59.000Z"),
    )


def build_prematch_url(tournament_id, path=PATHS[0]):
    start_date, end_date = _date_window()
    params = [
        ("startDate", start_date),
        ("endDate", end_date),
        ("period", "0"),
        ("tournamentId", str(tournament_id)),
    ]
    for stake in STAKE_TYPES:
        params.append(("stakeTypes", str(stake)))
    params.extend(
        [
            ("isTournament", "false"),
            ("eventFilterType", "false"),
            ("includeLiveEvents", "false"),
            ("langId", "2"),
            ("partnerId", "107"),
            ("countryCode", "KE"),
        ]
    )
    return SPORT_HOST + path + "?" + urlencode(params)


def extract_encrypted_payload(body, text=""):
    """Return the encrypted payload string, or None if this is not a feed body."""
    if isinstance(body, dict):
        payload = body.get("payload") or body.get("Payload")
        if isinstance(payload, str) and len(payload.strip()) > 20:
            return payload
        return None
    if isinstance(body, str) and len(body.strip()) > 20 and not _looks_like_html(body):
        return body
    if text and not _looks_like_html(text) and len(text.strip()) > 20:
        return text
    return None


def _looks_like_html(text: str) -> bool:
    head = text.lstrip()[:200].lower()
    return head.startswith("<!doctype") or "<html" in head


def looks_like_cloudflare(status=None, text: str = "", content_type: str = "") -> bool:
    """True when sport.bksp3.com returned a Cloudflare challenge instead of JSON."""
    head = (text or "").lstrip()[:800].lower()
    ctype = (content_type or "").lower()
    challenge = (
        "just a moment" in head
        or "cf-browser-verification" in head
        or "challenge-platform" in head
        or "cdn-cgi/challenge" in head
        or ("cloudflare" in head and _looks_like_html(text or ""))
    )
    if not challenge:
        return False
    if status in (403, 503, 429, 200) or status is None:
        return True
    return "text/html" in ctype or _looks_like_html(text or "")


def _fetch_mode() -> str:
    return os.getenv("BETKANYON_PREMATCH_FETCH", "auto").strip().lower()


def _use_zenrows_fallback() -> bool:
    return _fetch_mode() in {"zenrows", "browser"}


class BetkanyonPrematchHttpFetcher:
    """Persistent requests.Session against sport.bksp3.com. No browser."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.initialized = False
        self._working_path = PATHS[0]
        self.cloudflare_blocked = False

    def _connect(self):
        if self.initialized:
            return
        print("[BETKANYON PREMATCH] direct HTTP session started (no ZenRows)")
        self.initialized = True

    def _get_payload(self, url: str):
        try:
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
        except Exception:
            return None
        text = response.text or ""
        headers = getattr(response, "headers", None) or {}
        content_type = ""
        if hasattr(headers, "get"):
            content_type = headers.get("Content-Type") or headers.get("content-type") or ""
        if looks_like_cloudflare(response.status_code, text, content_type):
            if not self.cloudflare_blocked:
                print(
                    "[BETKANYON PREMATCH] Cloudflare blocked direct HTTP "
                    f"(status={response.status_code}); payloads will not relay "
                    "until Chrome CDP failover"
                )
            self.cloudflare_blocked = True
            return None
        if response.status_code >= 400:
            return None
        body = None
        try:
            body = response.json()
        except Exception:
            body = None
        return extract_encrypted_payload(body, text)

    def _fetch_chunk(self, urls):
        return [self._get_payload(url) for url in urls]

    def fetch_tournament(self, tournament_id):
        payloads = self.fetch_all([tournament_id])
        return payloads.get(str(tournament_id))

    def fetch_all(self, tournament_ids):
        self._connect()
        ids = [str(tid) for tid in tournament_ids]
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
                payloads = self._fetch_chunk(urls)
                if self.cloudflare_blocked:
                    break
                if any(payloads):
                    self._working_path = path
                    break
            if self.cloudflare_blocked:
                print(
                    "[BETKANYON PREMATCH] stopping HTTP sweep after Cloudflare "
                    f"(payloads={len(results)}/{total})"
                )
                break
            for tid, payload in zip(chunk, payloads or []):
                if payload:
                    results[tid] = payload
            done = min(offset + FETCH_BATCH_SIZE, total)
            if done == total or done % 40 == 0 or offset == 0:
                print(
                    f"[BETKANYON PREMATCH] fetch progress: {done}/{total} "
                    f"(payloads={len(results)})"
                )
        return results

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass
        self.initialized = False


def create_prematch_fetcher():
    return BetkanyonPrematchFetcher()


class BetkanyonPrematchFetcher:
    """Default name used by feed.py. auto = HTTP then local Chrome CDP."""

    def __init__(self):
        self._mode = _fetch_mode()
        self._impl = None
        if self._mode in {"zenrows", "browser"}:
            from parsers.betkanyon_prematch.fetcher_zenrows import (
                BetkanyonPrematchZenrowsFetcher,
            )

            print("[BETKANYON PREMATCH] BETKANYON_PREMATCH_FETCH=zenrows")
            self._impl = BetkanyonPrematchZenrowsFetcher()
        elif self._mode in {"cdp", "chrome", "local"}:
            from parsers.betkanyon_prematch.fetcher_cdp import (
                BetkanyonPrematchCdpFetcher,
            )

            print("[BETKANYON PREMATCH] BETKANYON_PREMATCH_FETCH=cdp (local Chrome)")
            self._impl = BetkanyonPrematchCdpFetcher()
        else:
            self._impl = BetkanyonPrematchHttpFetcher()

    def fetch_tournament(self, tournament_id):
        payloads = self.fetch_all([tournament_id])
        return payloads.get(str(tournament_id))

    def fetch_all(self, tournament_ids):
        payloads = self._impl.fetch_all(tournament_ids)
        if self._should_failover_to_cdp(payloads):
            from parsers.betkanyon_prematch.fetcher_cdp import (
                BetkanyonPrematchCdpFetcher,
            )

            print(
                "[BETKANYON PREMATCH] Cloudflare blocked direct HTTP; "
                "relaying payloads through local Chrome CDP"
            )
            try:
                self._impl.close()
            except Exception:
                pass
            self._impl = BetkanyonPrematchCdpFetcher()
            payloads = self._impl.fetch_all(tournament_ids)
        return payloads

    def _should_failover_to_cdp(self, payloads) -> bool:
        if self._mode not in {"auto", ""}:
            return False
        if not isinstance(self._impl, BetkanyonPrematchHttpFetcher):
            return False
        return bool(getattr(self._impl, "cloudflare_blocked", False))

    def close(self):
        if self._impl is not None:
            try:
                self._impl.close()
            except Exception:
                pass
            self._impl = None
