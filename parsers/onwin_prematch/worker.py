"""Persistent OnWin prematch worker.

Separate thread and ZenRows session from live OnWin. Target refresh
~90s. Does not import parsers.onwin.feed or parsers.onwin.worker.
"""

import os
import threading
import time

from engine.collector_health import (
    INPLACE_RETRY_PAUSE_SECONDS,
    MAX_INPLACE_RETRIES,
    is_connection_dead_error,
)
from parsers.onwin_prematch.feed import OnwinPrematchFeed

POLL_INTERVAL = float(os.getenv("ONWIN_PREMATCH_POLL_INTERVAL", "90"))
INITIAL_BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 60


class OnwinPrematchWorker:
    def __init__(self, poll_interval=POLL_INTERVAL):
        self.poll_interval = poll_interval
        self._feed = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = None
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
            "last_processing_ms": None,
            "avg_processing_ms": None,
            "last_event_count": 0,
            "last_odds_count": 0,
        }

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        print("[ONWIN PREMATCH] STARTING")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="onwin-prematch-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout=15):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        with self._lock:
            self._state["status"] = "stopped"

    def get_matches(self):
        with self._lock:
            return list(self._state["matches"])

    def get_status(self):
        with self._lock:
            return dict(self._state)

    def _run(self):
        try:
            self._run_loop()
        except Exception as exc:
            with self._lock:
                self._state["status"] = "error"
                self._state["error"] = type(exc).__name__
            print(f"[ONWIN PREMATCH] Worker thread crashed ({type(exc).__name__})")
        finally:
            self._close_feed()

    def _close_feed(self):
        feed = self._feed
        self._feed = None
        if feed is None:
            return
        try:
            feed.close()
        except Exception:
            pass

    def _run_loop(self):
        backoff = INITIAL_BACKOFF_SECONDS
        while not self._stop_event.is_set():
            cycle_start = time.monotonic()
            with self._lock:
                self._state["last_attempt_at"] = time.time()
            try:
                if self._feed is None:
                    with self._lock:
                        self._state["status"] = "connecting"
                    self._feed = OnwinPrematchFeed()
                    with self._lock:
                        self._state["reconnect_count"] += 1

                matches = self._feed.collect_once()
                elapsed_ms = (time.monotonic() - cycle_start) * 1000
                self._publish_success(matches, elapsed_ms)
                print(f"[ONWIN PREMATCH] MatchOdds produced: {len(matches)}")
                remaining = max(0.0, self.poll_interval - (elapsed_ms / 1000.0))
                print(f"[ONWIN PREMATCH] next refresh in {remaining:.0f}s")
                backoff = INITIAL_BACKOFF_SECONDS
            except Exception as exc:
                consecutive = self._publish_failure(exc)
                if is_connection_dead_error(exc) or consecutive >= MAX_INPLACE_RETRIES:
                    print(
                        f"[ONWIN PREMATCH] cycle failed "
                        f"({type(exc).__name__}); reconnecting in {backoff}s"
                    )
                    self._close_feed()
                    if self._stop_event.wait(timeout=backoff):
                        break
                    backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                else:
                    print(
                        f"[ONWIN PREMATCH] transient error "
                        f"({type(exc).__name__}); retrying in place"
                    )
                    if self._stop_event.wait(timeout=INPLACE_RETRY_PAUSE_SECONDS):
                        break
                continue

            remaining = self.poll_interval - (time.monotonic() - cycle_start)
            if remaining > 0 and self._stop_event.wait(timeout=remaining):
                break

    def _publish_success(self, matches, elapsed_ms):
        with self._lock:
            state = self._state
            state["status"] = "running"
            state["error"] = None
            state["last_update_at"] = time.time()
            state["poll_count"] += 1
            state["success_count"] += 1
            state["consecutive_failures"] = 0
            state["consecutive_successes"] += 1
            state["last_processing_ms"] = elapsed_ms
            if matches or not state["matches"]:
                state["matches"] = matches
                state["last_event_count"] = (
                    self._feed.get_parsed_event_count() if self._feed else 0
                )
                state["last_odds_count"] = len(matches)
            prev_avg = state["avg_processing_ms"]
            n = state["success_count"]
            state["avg_processing_ms"] = (
                elapsed_ms if prev_avg is None
                else prev_avg + (elapsed_ms - prev_avg) / n
            )

    def _publish_failure(self, exc) -> int:
        with self._lock:
            state = self._state
            state["error"] = type(exc).__name__
            state["poll_count"] += 1
            state["failed_count"] += 1
            state["consecutive_successes"] = 0
            state["consecutive_failures"] += 1
            return state["consecutive_failures"]
