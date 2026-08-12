"""
Persistent BetKanyon acquisition worker.

BetKanyon's existing acquisition mechanism (parsers/betkanyon/feed.py ->
fetcher.py -> browser.py -> decryptor.py -> parser.py -> adapter.py) is
NOT event-driven like OnWin's find_event_snapshots feed -- it's a pull:
call fetch() on the already-open, already-authenticated page and get
back one fresh encrypted payload.

That is actually convenient here: BetkanyonFetcher already lazily opens
its browser/session once (see BetkanyonFetcher._connect()/initialized)
and already has its own reconnect-on-failure logic
(BetkanyonFetcher._reset_browser()). All that was missing was something
that keeps ONE BetkanyonFeed alive and calls collect_once() on a tight,
non-overlapping schedule instead of creating/destroying a feed (and its
browser) every 20 seconds.

Threading, not another process:
Playwright's sync API is not compatible with a thread that is *also*
running an asyncio event loop. BetKanyon's polling loop has no such
loop -- it's just fetch -> decrypt (subprocess) -> parse -> adapt in a
tight sequential cycle -- so this can safely run as a plain background
thread inside the same process as the collector, sharing memory with a
lock instead of needing multiprocessing IPC like OnWin required for its
continuous Playwright event-listener architecture.
"""

import os
import threading
import time
from datetime import datetime

from parsers.betkanyon.feed import BetkanyonFeed


# How often BetKanyon should acquire a fresh payload.
#
# This is a target MINIMUM spacing between the start of one cycle and
# the next, not a mandatory wait: if a cycle (fetch + decrypt + parse)
# takes longer than this, the next poll starts immediately afterward
# instead of waiting further. Configurable via env var rather than
# hard-coded in multiple places (worker + any caller that wants to
# reason about expected freshness).
BETKANYON_POLL_INTERVAL = float(os.getenv("BETKANYON_POLL_INTERVAL", "3"))

# Reconnect backoff: starts here after the first failure and doubles
# on each consecutive failure, capped at MAX_BACKOFF_SECONDS, so a
# persistent outage still retries periodically without hammering the
# site or spinning the CPU. Exposed as module constants (rather than
# literals inline in _run) so tests can override them.
INITIAL_BACKOFF_SECONDS = 3
MAX_BACKOFF_SECONDS = 60


class BetkanyonWorker:
    """
    Owns exactly ONE persistent BetKanyon browser/session (via one
    long-lived BetkanyonFeed) and polls it on a background thread.

    Thread-safe reads: get_matches()/get_status() copy out of a small
    dict under a lock, so the collector's engine tick never blocks on
    -- or overlaps with -- an in-flight poll.
    """

    def __init__(self, poll_interval: float = BETKANYON_POLL_INTERVAL):
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
            "poll_count": 0,
            "success_count": 0,
            "last_processing_ms": None,
            "avg_processing_ms": None,
            "last_event_count": 0,
            "last_odds_count": 0,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return

        print("[BETKANYON] Starting persistent browser...")

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="betkanyon-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout=10):
        self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=timeout)

        if self._feed is not None:
            try:
                self._feed.close()
            except Exception:
                pass
            self._feed = None

        with self._lock:
            self._state["status"] = "stopped"

    # ------------------------------------------------------------------
    # Reads (called from the collector/engine side)
    # ------------------------------------------------------------------

    def get_matches(self):
        with self._lock:
            return list(self._state["matches"])

    def get_status(self):
        with self._lock:
            return dict(self._state)

    # ------------------------------------------------------------------
    # Worker loop
    # ------------------------------------------------------------------

    def _run(self):
        backoff = INITIAL_BACKOFF_SECONDS

        while not self._stop_event.is_set():

            cycle_start = time.monotonic()

            try:
                if self._feed is None:
                    with self._lock:
                        self._state["status"] = "connecting"

                    self._feed = BetkanyonFeed()

                matches = self._feed.collect_once()
                elapsed_ms = (time.monotonic() - cycle_start) * 1000

                first_success = self._state["success_count"] == 0

                self._publish_success(matches, elapsed_ms)

                if first_success:
                    print("[BETKANYON] Session established")
                    print("[BETKANYON] Encrypted feed active")

                now_str = datetime.now().strftime("%H:%M:%S")

                print(
                    f"[BETKANYON] {now_str} | payload received | "
                    f"events={self._feed.get_parsed_event_count()} | "
                    f"odds={len(matches)}"
                )
                print(
                    f"[BETKANYON] {now_str} | processed in "
                    f"{elapsed_ms:.0f}ms | state age=0.0s"
                )

                backoff = INITIAL_BACKOFF_SECONDS  # reset after a clean cycle

            except Exception as exc:
                self._publish_failure(exc)

                print(
                    f"[BETKANYON] Cycle failed "
                    f"({type(exc).__name__}: {exc}). "
                    f"Reconnecting in {backoff}s..."
                )

                if self._feed is not None:
                    try:
                        self._feed.close()
                    except Exception:
                        pass
                    self._feed = None

                if self._stop_event.wait(timeout=backoff):
                    break

                backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
                continue

            elapsed = time.monotonic() - cycle_start
            remaining = self.poll_interval - elapsed

            if remaining > 0:
                # Interruptible wait so stop() doesn't have to wait out
                # a full idle period.
                if self._stop_event.wait(timeout=remaining):
                    break
            # else: the cycle itself already took >= poll_interval,
            # so we go straight into the next poll (no overlapping
            # requests, just no artificial extra delay either).

    def _publish_success(self, matches, elapsed_ms):
        with self._lock:
            state = self._state

            state["matches"] = matches
            state["status"] = "running"
            state["error"] = None
            state["last_update_at"] = time.time()
            state["poll_count"] += 1
            state["success_count"] += 1
            state["last_processing_ms"] = elapsed_ms
            state["last_event_count"] = self._feed.get_parsed_event_count()
            state["last_odds_count"] = len(matches)

            prev_avg = state["avg_processing_ms"]
            n = state["success_count"]

            state["avg_processing_ms"] = (
                elapsed_ms if prev_avg is None
                else prev_avg + (elapsed_ms - prev_avg) / n
            )

    def _publish_failure(self, exc):
        with self._lock:
            state = self._state
            state["status"] = "reconnecting"
            state["error"] = f"{type(exc).__name__}: {exc}"
            state["poll_count"] += 1
