"""Persistent Kolay90 prematch feed.

Owns one ZenRows browser session. Polls getMaclar from that page.
Never treats auth/network failure as an empty book.
Does not close the browser unless close() is called.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from parsers.kolay90_prematch.browser import Kolay90PrematchBrowser
from parsers.kolay90_prematch.fetch import fetch_getmaclar
from parsers.kolay90_prematch.login import establish_session
from parsers.kolay90_prematch.parser import count_oranlar, parse_payload, unwrap_events


class Kolay90PrematchFeed:
    def __init__(self):
        self.browser = Kolay90PrematchBrowser()
        self._page = None
        self._last_good: list = []
        self._degraded: str | None = None
        self._session_ready = False

    def start(self) -> dict:
        self._page = self.browser.page()
        login = establish_session(self._page)
        if not login.get("ok"):
            self._degraded = login.get("reason") or "session_failed"
            return login
        probe = fetch_getmaclar(self._page)
        if login.get("login_form_submitted") and probe.get("unauthenticated"):
            deadline = time.time() + 30
            while time.time() < deadline and probe.get("unauthenticated"):
                self._page.wait_for_timeout(2000)
                probe = fetch_getmaclar(self._page)
        classified = self._apply_fetch(probe)
        login["getmaclar"] = {k: v for k, v in classified.items() if k != "matches"}
        if classified.get("authenticated"):
            self._session_ready = True
            self._degraded = None
        else:
            self._degraded = classified.get("failure") or "unauthenticated"
            login["ok"] = False
            login["reason"] = self._degraded
        return login

    def poll(self) -> dict:
        if self._page is None or self._page.is_closed():
            self._degraded = "browser_page_closed"
            return {
                "ok": False,
                "failure": self._degraded,
                "matches": list(self._last_good),
                "kept_last_good": True,
            }
        raw = fetch_getmaclar(self._page)
        return self._apply_fetch(raw)

    def _apply_fetch(self, raw: dict) -> dict:
        status = raw.get("status")
        payload = raw.get("payload")
        failure = None
        authenticated = False
        if raw.get("error"):
            failure = f"network:{raw.get('error')}"
        elif raw.get("cloudflare") or (raw.get("looks_html") and not raw.get("json")):
            failure = "cloudflare_html"
        elif status in (401, 403):
            failure = f"http_{status}"
        elif raw.get("unauthenticated"):
            failure = "login_expired"
        elif not raw.get("json"):
            failure = "non_json"
        else:
            events = unwrap_events(payload)
            matches = parse_payload(payload)
            counts = count_oranlar(events)
            if events or matches:
                authenticated = True
                self._last_good = matches
                self._degraded = None
                return {
                    "ok": True,
                    "authenticated": True,
                    "status": status,
                    "content_type": raw.get("content_type"),
                    "bytes": raw.get("bytes"),
                    "total_events": len(events),
                    "one_x_two": len(matches),
                    "with_any_1x2": counts["with_any_1x2"],
                    "with_all_1x2": counts["with_all_1x2"],
                    "matches": matches,
                    "kept_last_good": False,
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                }
            failure = "empty_or_unparsed"
        self._degraded = failure
        return {
            "ok": False,
            "authenticated": authenticated,
            "failure": failure,
            "status": status,
            "content_type": raw.get("content_type"),
            "bytes": raw.get("bytes"),
            "total_events": 0,
            "one_x_two": len(self._last_good),
            "with_any_1x2": 0,
            "with_all_1x2": 0,
            "matches": list(self._last_good),
            "kept_last_good": bool(self._last_good),
        }

    def last_good(self) -> list:
        return list(self._last_good)

    def degraded(self) -> str | None:
        return self._degraded
