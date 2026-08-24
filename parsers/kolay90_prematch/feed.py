"""Kolay90 prematch feed attached to one persistent local Chrome session.

Polls getMaclar from the already-authenticated page via in-page fetch.
Never launches or closes Chrome. Never uses ZenRows or cookie replay.
A bad cycle keeps the last-good MatchOdds snapshot.
"""

from __future__ import annotations

from datetime import datetime, timezone

from parsers.kolay90_prematch.cdp import attach_kolay90_page, detach
from parsers.kolay90_prematch.fetch import fetch_getmaclar
from parsers.kolay90_prematch.parser import (
    count_oranlar,
    parse_payload,
    to_match_odds,
    unwrap_events,
)
from parsers.kolay90_prematch.session_state import (
    AUTH_REQUIRED,
    classify_page,
    failure_for_state,
    is_auth_required_state,
)

AUTH_FAILURES = {
    "login_expired",
    "cloudflare_challenge",
    "cloudflare_html",
    "agreement_page",
    "login_page",
    "authentication_required",
    "cdp_attach_failed",
    "kolay90_tab_missing",
}


class Kolay90PrematchFeed:
    def __init__(self, cdp_endpoint: str | None = None):
        self.cdp_endpoint = cdp_endpoint
        self._playwright = None
        self._browser = None
        self._page = None
        self._last_good: list = []
        self._degraded: str | None = None
        self._session_ready = False
        self._auth_state: str | None = None
        self._page_identity = None

    def attach(self) -> dict:
        if self._page is not None and not self._page_closed():
            return {
                "ok": True,
                "reused": True,
                "url": getattr(self._page, "url", ""),
                "title": self._safe_title(),
            }
        if self._playwright is not None:
            detach(self._playwright)
            self._playwright = None
            self._browser = None
            self._page = None
        try:
            attached = attach_kolay90_page(self.cdp_endpoint)
        except Exception as exc:
            self._degraded = "cdp_attach_failed"
            self._auth_state = AUTH_REQUIRED
            return {
                "ok": False,
                "failure": self._degraded,
                "error": type(exc).__name__,
                "auth_state": AUTH_REQUIRED,
            }
        self._playwright = attached["playwright"]
        self._browser = attached["browser"]
        self._page = attached["page"]
        if self._page is None:
            self._degraded = "kolay90_tab_missing"
            self._auth_state = AUTH_REQUIRED
            return {
                "ok": False,
                "failure": self._degraded,
                "pages": attached["pages"],
                "auth_state": AUTH_REQUIRED,
            }
        self._page_identity = id(self._page)
        state = classify_page(self._page)
        self._auth_state = state
        if is_auth_required_state(state):
            self._degraded = failure_for_state(state)
            return {
                "ok": False,
                "failure": self._degraded,
                "auth_state": AUTH_REQUIRED,
                "session_state": state,
                "url": attached.get("url"),
                "title": attached.get("title"),
            }
        self._session_ready = True
        self._degraded = None
        return {
            "ok": True,
            "reused": False,
            "session_state": state,
            "url": attached.get("url"),
            "title": attached.get("title"),
            "pages": attached["pages"],
        }

    def start(self) -> dict:
        return self.attach()

    def poll(self) -> dict:
        attached = self.attach()
        if not attached.get("ok"):
            return self._keep_last_good(attached.get("failure") or "cdp_attach_failed")
        if self._page is None or self._page_closed():
            return self._keep_last_good("browser_page_closed")
        state = classify_page(self._page)
        self._auth_state = state
        if is_auth_required_state(state):
            return self._keep_last_good(failure_for_state(state), session_state=state)
        raw = fetch_getmaclar(self._page)
        return self._apply_fetch(raw, session_state=state)

    def _apply_fetch(self, raw: dict, session_state: str | None = None) -> dict:
        status = raw.get("status")
        payload = raw.get("payload")
        failure = None
        if raw.get("error"):
            failure = f"network:{raw.get('error')}"
        elif raw.get("cloudflare") or (raw.get("looks_html") and not raw.get("json")):
            failure = "cloudflare_html"
        elif status in (401, 403):
            failure = f"http_{status}"
            prefix = ""
            if isinstance(raw.get("payload"), dict):
                prefix = "json"
            elif raw.get("looks_html"):
                prefix = "html"
            print(
                f"[KOLAY90 PREMATCH] getMaclar {status} "
                f"ctype={raw.get('content_type')} body={prefix or 'other'}"
            )
        elif raw.get("unauthenticated"):
            failure = "login_expired"
        elif not raw.get("json"):
            failure = "non_json"
        else:
            events = unwrap_events(payload)
            parsed = parse_payload(payload)
            matches = to_match_odds(parsed)
            counts = count_oranlar(events)
            if matches:
                self._last_good = matches
                self._degraded = None
                self._session_ready = True
                self._auth_state = session_state or "AUTHENTICATED_APP"
                return {
                    "ok": True,
                    "authenticated": True,
                    "auth_state": self._auth_state,
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
        return self._keep_last_good(
            failure,
            status=status,
            content_type=raw.get("content_type"),
            bytes=raw.get("bytes"),
            session_state=session_state,
        )

    def _keep_last_good(
        self,
        failure: str | None,
        status=None,
        content_type=None,
        bytes=None,
        session_state: str | None = None,
    ) -> dict:
        self._degraded = failure
        auth_required = failure in AUTH_FAILURES or is_auth_required_state(session_state)
        if auth_required:
            self._auth_state = AUTH_REQUIRED
        return {
            "ok": False,
            "authenticated": False,
            "auth_required": auth_required,
            "auth_state": AUTH_REQUIRED if auth_required else session_state,
            "failure": failure,
            "status": status,
            "content_type": content_type,
            "bytes": bytes,
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

    def auth_state(self) -> str | None:
        return self._auth_state

    def page_identity(self):
        return self._page_identity

    def _page_closed(self) -> bool:
        try:
            return bool(self._page is not None and self._page.is_closed())
        except Exception:
            return True

    def _safe_title(self) -> str:
        try:
            return (self._page.title() or "")[:120]
        except Exception:
            return ""

    def close(self) -> None:
        """Detach CDP only. Leaves the operator Chrome process running."""
        self._page = None
        self._browser = None
        self._page_identity = None
        playwright = self._playwright
        self._playwright = None
        detach(playwright)
