"""Persistent OnWin prematch feed.

Navigates the prelive soccer main-line once per cycle on ONE ZenRows
page, intercepts get_main_line.erisgaming (same endpoint as live), and
parses prematch MatchOdds. Empty/thin payloads keep the last-good list.

Does not import or modify parsers.onwin.feed.OnwinFeed.
"""

from __future__ import annotations

import json
import time

from parsers.onwin_prematch.browser import OnwinPrematchBrowser
from parsers.onwin_prematch.parser import parse_prematch, unwrap_payload

PRELIVE_PAGE = "https://onwin4511.com/sportsbook/prelive/main-line/soccer"
TARGET = "get_main_line.erisgaming"
UPDATE_FRAGMENTS = (
    "find_event_snapshots.erisgaming",
    "get_main_line_gap.erisgaming",
)
CAPTURE_TIMEOUT_S = 180


def _is_full_sports_tree(data) -> bool:
    payload = unwrap_payload(data)
    if not isinstance(payload, dict):
        return False
    sports = payload.get("sports")
    return isinstance(sports, dict) and bool(sports)


class OnwinPrematchFeed:
    def __init__(self):
        self.browser = OnwinPrematchBrowser()
        self._page = None
        self._latest = None
        self._last_good: list = []
        self.last_stats = {"events": 0, "odds": 0}

    def _read_body(self, request):
        try:
            response = request.response()
            if response is None or response.status != 200:
                return None
            body = response.body()
            if not body:
                return None
            return json.loads(body.decode("utf-8", errors="replace"))
        except Exception:
            return None

    def _on_finished(self, request):
        url = request.url or ""
        if TARGET not in url and not any(fragment in url for fragment in UPDATE_FRAGMENTS):
            return
        data = self._read_body(request)
        if data is None:
            return
        if TARGET in url and _is_full_sports_tree(data):
            self._latest = data
            return
        if self._latest is None and _is_full_sports_tree(data):
            self._latest = data

    def _ensure_page(self):
        if self._page is not None and not self._page.is_closed():
            return
        page = self.browser.page()
        page.on("requestfinished", self._on_finished)
        self._page = page

    def _goto(self):
        try:
            self._page.goto(
                PRELIVE_PAGE,
                wait_until="domcontentloaded",
                timeout=120000,
            )
        except Exception as exc:
            print(
                f"[ONWIN PREMATCH] navigation {type(exc).__name__}",
                flush=True,
            )

    def _wait_for_tree(self, timeout_s: int = CAPTURE_TIMEOUT_S) -> bool:
        started = time.monotonic()
        while time.monotonic() - started < timeout_s:
            if self._latest is not None and _is_full_sports_tree(self._latest):
                return True
            if self._page is None or self._page.is_closed():
                return False
            self._page.wait_for_timeout(500)
        return self._latest is not None and _is_full_sports_tree(self._latest)

    def collect_once(self) -> list:
        self._ensure_page()
        previous = self._latest
        # Drop the previous handle so this cycle waits for a fresh
        # full sports tree instead of returning the last capture
        # immediately. Thin get_main_line bodies never replace it.
        self._latest = None
        self._goto()
        got = self._wait_for_tree()
        if not got:
            self._latest = previous
            if self._last_good:
                print("[ONWIN PREMATCH] kept last-good snapshot (no full tree)")
                return list(self._last_good)
            raise RuntimeError(
                "get_main_line.erisgaming was not captured with a sports tree"
            )
        matches = parse_prematch(self._latest)
        self.last_stats = {
            "events": len(matches),
            "odds": len(matches),
        }
        if matches:
            self._last_good = matches
            return matches
        if self._last_good:
            print("[ONWIN PREMATCH] kept last-good snapshot (empty parse)")
            return list(self._last_good)
        return []

    def get_parsed_event_count(self) -> int:
        return self.last_stats.get("events") or 0

    def close(self):
        try:
            self.browser.close()
        except Exception:
            pass
        self._page = None
