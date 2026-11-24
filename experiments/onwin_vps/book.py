"""Record Onwin VPS collection results without touching production.

A success timestamp moves only when usable odds were parsed. A failed
post, an empty body, or a browser that is merely open does not count.
"""

from __future__ import annotations

from datetime import datetime, timezone


def _iso(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    return current.astimezone(timezone.utc).isoformat()


class CollectionBook:
    def __init__(self):
        self.live_odds = 0
        self.prematch_odds = 0
        self.live_events = 0
        self.prematch_events = 0
        self.live_markets = 0
        self.prematch_markets = 0
        self.live_requests = 0
        self.prematch_requests = 0
        self.snapshots_seen = 0
        self.updates_seen = 0
        self.responses_received = 0
        self.last_live_success = None
        self.last_prematch_success = None
        self.last_live_poll_ms = None
        self.last_prematch_poll_ms = None
        self.last_error = None
        self.attached = False
        self.chrome_listening = False
        self.page_loaded = False
        self.session_valid = None
        self.recovery_attempts = 0
        self.live_page = ""
        self.prematch_page = ""
        self.phase = "starting"

    def note_traffic(self, kind: str, lane: str) -> None:
        if kind == "snapshot":
            self.snapshots_seen += 1
        elif kind == "update":
            self.updates_seen += 1
        if lane == "live":
            self.live_requests += 1
        elif lane == "prematch":
            self.prematch_requests += 1

    def note_response(self) -> None:
        self.responses_received += 1

    def note_odds(
        self,
        lane: str,
        odds: int,
        *,
        events: int = 0,
        markets: int = 0,
        publish_ok: bool | None,
        poll_ms: float | None = None,
        from_network: bool = True,
        now: datetime | None = None,
    ) -> bool:
        """Return True only when this observation is a successful collection.

        publish_ok is None when production ingest is switched off.
        False means the VPS refused the post, so the previous success stands.
        A republish of odds already in memory does not count as a new
        collection while ingest is off.
        """
        if lane == "live":
            self.last_live_poll_ms = poll_ms
        elif lane == "prematch":
            self.last_prematch_poll_ms = poll_ms
        else:
            return False
        if not from_network and publish_ok is None:
            return False
        if odds <= 0 or publish_ok is False:
            return False
        stamp = _iso(now)
        if lane == "live":
            self.live_odds = odds
            self.live_events = events
            self.live_markets = markets
            self.last_live_success = stamp
        else:
            self.prematch_odds = odds
            self.prematch_events = events
            self.prematch_markets = markets
            self.last_prematch_success = stamp
        self.session_valid = True
        self.last_error = None
        return True

    def status(self, *, publish: bool, cdp_url: str, profile: str) -> dict:
        return {
            "zenrows_used": False,
            "playwright_browser_launched": False,
            "publish_to_engine": publish,
            "cdp_url": cdp_url,
            "profile": profile,
            "chrome_listening": self.chrome_listening,
            "attached": self.attached,
            "phase": self.phase,
            "page_loaded": self.page_loaded,
            "session_valid": self.session_valid,
            "live_page": self.live_page,
            "prematch_page": self.prematch_page,
            "get_main_line_seen": self.snapshots_seen,
            "updates_seen": self.updates_seen,
            "responses_received": self.responses_received,
            "live_requests": self.live_requests,
            "prematch_requests": self.prematch_requests,
            "live_events": self.live_events,
            "prematch_events": self.prematch_events,
            "live_markets": self.live_markets,
            "prematch_markets": self.prematch_markets,
            "live_odds": self.live_odds,
            "prematch_odds": self.prematch_odds,
            "last_live_success": self.last_live_success,
            "last_prematch_success": self.last_prematch_success,
            "last_live_poll_ms": self.last_live_poll_ms,
            "last_prematch_poll_ms": self.last_prematch_poll_ms,
            "recovery_attempts": self.recovery_attempts,
            "last_error": self.last_error,
        }
