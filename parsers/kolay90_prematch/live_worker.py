"""Kolay91 live collector.

Polls getMaclar and the live/upcoming endpoint on independent 5-second
schedules. Both requests use the authenticated Kolay91 Chrome tab.
One endpoint failing does not clear the other endpoint's last good odds.
The prematch worker is a separate object and is not updated here.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone

from parsers.kolay90_prematch.cdp import attach_kolay90_page, detach
from parsers.kolay90_prematch.fetch import fetch_url
from parsers.kolay90_prematch.live import (
    ENDPOINTS,
    POLL_INTERVAL_SECONDS,
    PollSlot,
    claim_due,
    diagnose,
    merge_matches,
    parse_endpoint_payload,
    retry_after_seconds,
    schedule_after,
)
from parsers.kolay90_prematch.parser import to_match_odds, unwrap_events

FETCH_TIMEOUT_MS = int(os.getenv("KOLAY90_LIVE_FETCH_TIMEOUT_MS", "4000"))


def poll_interval_seconds() -> float:
    try:
        value = float(os.getenv("KOLAY90_LIVE_POLL_INTERVAL", str(POLL_INTERVAL_SECONDS)))
    except ValueError:
        value = POLL_INTERVAL_SECONDS
    return value if value > 0 else POLL_INTERVAL_SECONDS


class Kolay90LiveWorker:
    def __init__(self, poll_interval: float | None = None, fetcher=None):
        self.poll_interval = poll_interval_seconds() if poll_interval is None else poll_interval
        self._fetcher = fetcher
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
        self._playwright = None
        self._page = None
        self._slots = {name: PollSlot(self.poll_interval) for name in ENDPOINTS}
        self._endpoint_matches = {name: [] for name in ENDPOINTS}
        self._state = {
            "matches": [],
            "status": "starting",
            "error": None,
            "last_update_at": None,
            "last_attempt_at": None,
            "poll_count": 0,
            "success_count": 0,
            "failed_count": 0,
            "consecutive_failures": 0,
            "consecutive_successes": 0,
            "reconnect_count": 0,
            "last_event_count": 0,
            "last_odds_count": 0,
            "endpoints": {
                name: {
                    "diagnosis": None,
                    "last_success_at": None,
                    "last_attempt_at": None,
                    "odds": 0,
                }
                for name in ENDPOINTS
            },
        }

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        print("[KOLAY90 LIVE] STARTING — attaching to existing Kolay91 Chrome")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="kolay90-live-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout=15):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._detach()
        with self._lock:
            self._state["status"] = "stopped"

    def get_matches(self):
        with self._lock:
            return list(self._state["matches"])

    def get_status(self):
        with self._lock:
            status = dict(self._state)
            status["endpoints"] = {
                name: dict(row) for name, row in self._state["endpoints"].items()
            }
            return status

    def _run(self):
        from engine.sync_playwright_thread import isolate_from_running_asyncio_loop

        isolate_from_running_asyncio_loop()
        try:
            self._run_loop()
        except Exception as exc:
            with self._lock:
                self._state["status"] = "error"
                self._state["error"] = f"{type(exc).__name__}: {exc}"
            print(f"[KOLAY90 LIVE] worker crashed ({type(exc).__name__}: {exc})")
        finally:
            self._detach()

    def _detach(self):
        playwright = self._playwright
        self._playwright = None
        self._page = None
        detach(playwright)

    def _ensure_page(self) -> bool:
        if self._fetcher is not None:
            return True
        try:
            closed = self._page is None or self._page.is_closed()
        except Exception:
            closed = True
        if not closed:
            return True
        self._detach()
        try:
            attached = attach_kolay90_page()
        except Exception as exc:
            self._note_attach_failure(type(exc).__name__)
            return False
        self._playwright = attached["playwright"]
        self._page = attached["page"]
        if self._page is None:
            self._note_attach_failure("kolay90_tab_missing")
            return False
        return True

    def _note_attach_failure(self, reason: str) -> None:
        with self._lock:
            self._state["error"] = reason
            self._state["failed_count"] += 1
            self._state["consecutive_failures"] += 1
            self._state["consecutive_successes"] = 0
            self._state["status"] = "degraded" if self._state["matches"] else "error"

    def _run_loop(self):
        while not self._stop_event.is_set():
            now = time.monotonic()
            name = claim_due(self._slots, now)
            if name is None:
                nxt = min(slot.next_monotonic for slot in self._slots.values())
                self._stop_event.wait(timeout=max(0.05, min(0.5, nxt - now)))
                continue
            slot = self._slots[name]
            slot.in_flight = True
            try:
                self._poll_endpoint(name, slot)
            finally:
                slot.in_flight = False

    def _poll_endpoint(self, name: str, slot: PollSlot) -> None:
        started = time.monotonic()
        with self._lock:
            self._state["last_attempt_at"] = time.time()
            self._state["poll_count"] += 1
            self._state["endpoints"][name]["last_attempt_at"] = time.time()
        if not self._ensure_page():
            schedule_after(slot, time.monotonic(), self.poll_interval, "network", None)
            return
        try:
            if self._fetcher is not None:
                raw = self._fetcher(name, ENDPOINTS[name])
            else:
                raw = fetch_url(self._page, ENDPOINTS[name], timeout_ms=FETCH_TIMEOUT_MS)
        except Exception as exc:
            raw = {
                "error": type(exc).__name__,
                "status": None,
                "json": False,
                "payload": None,
                "looks_html": False,
                "unauthenticated": False,
                "cloudflare": False,
                "retry_after": None,
            }
        collected = datetime.now(timezone.utc)
        payload = raw.get("payload")
        events = unwrap_events(payload) if raw.get("json") else []
        try:
            parsed = parse_endpoint_payload(name, payload, collected) if raw.get("json") else []
        except Exception:
            parsed = []
        diagnosis = diagnose(raw, len(events), len(parsed))
        matches = to_match_odds(parsed) if diagnosis == "ok" else list(self._endpoint_matches[name])
        if diagnosis == "ok":
            self._endpoint_matches[name] = matches
        merged = merge_matches(
            [match for rows in self._endpoint_matches.values() for match in rows]
        )
        elapsed_ms = (time.monotonic() - started) * 1000
        self._publish(name, diagnosis, matches if diagnosis == "ok" else [], merged, elapsed_ms)
        schedule_after(
            slot,
            time.monotonic(),
            self.poll_interval,
            diagnosis,
            retry_after_seconds(raw.get("retry_after")),
        )
        print(
            f"[KOLAY90 LIVE] {name} diagnosis={diagnosis} "
            f"odds={len(self._endpoint_matches[name])} "
            f"status={raw.get('status')} ms={elapsed_ms:.0f}"
        )

    def _publish(self, name: str, diagnosis: str, fresh: list, merged: list, elapsed_ms: float) -> None:
        del elapsed_ms
        with self._lock:
            state = self._state
            endpoint = state["endpoints"][name]
            endpoint["diagnosis"] = diagnosis
            if diagnosis == "ok":
                endpoint["odds"] = len(fresh)
                endpoint["last_success_at"] = time.time()
                state["matches"] = merged
                state["last_event_count"] = len(merged)
                state["last_odds_count"] = len(merged)
                state["status"] = "running"
                state["error"] = None
                state["last_update_at"] = time.time()
                state["success_count"] += 1
                state["consecutive_failures"] = 0
                state["consecutive_successes"] += 1
                return
            if diagnosis == "no_live_events":
                if state["status"] == "starting":
                    state["status"] = "running"
                return
            state["failed_count"] += 1
            state["consecutive_successes"] = 0
            now = time.time()
            other_fresh = any(
                row.get("last_success_at")
                and now - row["last_success_at"] <= self.poll_interval * 2
                for key, row in state["endpoints"].items()
                if key != name
            )
            state["error"] = f"{name}:{diagnosis}"
            if other_fresh:
                state["status"] = "running"
                return
            state["consecutive_failures"] += 1
            state["status"] = "degraded" if state["matches"] else "error"
