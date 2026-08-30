"""Persistent BetKanyon prematch worker.

Separate thread + separate browser from live BetKanyon. Target refresh
is ~90s, waiting only leftover time after fetch/decrypt/parse.
"""

import os
import threading
import time
from datetime import datetime

from credentials.errors import AllCredentialsUnavailableError
from engine.collector_health import (
    INPLACE_RETRY_PAUSE_SECONDS,
    MAX_INPLACE_RETRIES,
    is_connection_dead_error,
)
from parsers.betkanyon_prematch.feed import BetkanyonPrematchFeed


POLL_INTERVAL = float(os.getenv("BETKANYON_PREMATCH_POLL_INTERVAL", "90"))
INITIAL_BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 60
MAX_CREDENTIAL_WAIT_SECONDS = 3600


class BetkanyonPrematchWorker:
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
        print("[BETKANYON PREMATCH] STARTING")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="betkanyon-prematch-worker",
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
        from engine.sync_playwright_thread import isolate_from_running_asyncio_loop

        isolate_from_running_asyncio_loop()
        try:
            self._run_loop()
        except Exception as exc:
            with self._lock:
                self._state["status"] = "error"
                self._state["error"] = f"{type(exc).__name__}: {exc}"
            print(
                f"[BETKANYON PREMATCH] Worker thread crashed "
                f"({type(exc).__name__}: {exc})"
            )
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
                    self._feed = BetkanyonPrematchFeed()
                    print(
                        f"[BETKANYON PREMATCH] tournaments loaded: "
                        f"{len(self._feed.tournament_ids)}"
                    )

                matches = self._feed.collect_once()
                elapsed_ms = (time.monotonic() - cycle_start) * 1000
                self._publish_success(matches, elapsed_ms)
                stats = self._feed.last_stats
                remaining = max(0.0, self.poll_interval - (elapsed_ms / 1000.0))
                print(
                    f"[BETKANYON PREMATCH] events discovered: {stats['events']}"
                )
                print(
                    f"[BETKANYON PREMATCH] 1X2 markets discovered: "
                    f"{stats.get('match_odds_markets', 0)}"
                )
                print(
                    f"[BETKANYON PREMATCH] MatchOdds produced: {stats['odds']}"
                )
                print("[BETKANYON PREMATCH] state updated")
                print(
                    f"[BETKANYON PREMATCH] next refresh in {remaining:.0f}s"
                )
                backoff = INITIAL_BACKOFF_SECONDS
            except AllCredentialsUnavailableError as exc:
                self._publish_failure(exc)
                wait = min(
                    exc.retry_after_seconds or backoff,
                    MAX_BACKOFF_SECONDS,
                )
                print(
                    f"[BETKANYON PREMATCH] credentials unavailable; "
                    f"retry in {wait:.0f}s"
                )
                self._close_feed()
                if self._stop_event.wait(timeout=max(wait, 2.0)):
                    break
                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                continue
            except Exception as exc:
                consecutive = self._publish_failure(exc)
                if is_connection_dead_error(exc) or consecutive >= MAX_INPLACE_RETRIES:
                    print(
                        f"[BETKANYON PREMATCH] cycle failed "
                        f"({type(exc).__name__}: {exc}); reconnecting in {backoff}s"
                    )
                    self._close_feed()
                    if self._stop_event.wait(timeout=backoff):
                        break
                    backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                else:
                    print(
                        f"[BETKANYON PREMATCH] transient error "
                        f"({type(exc).__name__}: {exc}); retrying in place"
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
            state["error"] = f"{type(exc).__name__}: {exc}"
            state["poll_count"] += 1
            state["failed_count"] += 1
            state["consecutive_successes"] = 0
            state["consecutive_failures"] += 1
            return state["consecutive_failures"]
