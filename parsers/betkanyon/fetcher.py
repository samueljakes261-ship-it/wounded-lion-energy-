"""BetKanyon LIVE acquisition via direct HTTP. No ZenRows, no Playwright."""

from __future__ import annotations

import time

import requests

from parsers.betkanyon_prematch.fetcher import extract_encrypted_payload


LIVE_PAGE = "https://betkanyon1617.com/tr/sport/live"
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
    "Origin": "https://betkanyon1617.com",
    "Referer": LIVE_PAGE,
}


class EmptyAcquisitionError(RuntimeError):
    """HTTP completed but no usable encrypted payload was returned."""


class BetkanyonFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.initialized = False
        self.last_meta = {
            "http_status": None,
            "content_type": None,
            "payload_bytes": 0,
        }

    def _connect(self):
        if self.initialized:
            return
        print("[BETKANYON] direct HTTP session started (no ZenRows)")
        self.initialized = True

    def fetch(self):
        self._connect()
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

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass
        self.initialized = False
