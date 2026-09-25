"""
Base persistent worker for the Kenyan Bookmakers module.

Architecture (per the task's explicit requirement):

    worker starts
        -> initial acquisition
        -> parse payload
        -> update bookmaker snapshot
        -> wait 5 seconds
        -> poll again
        -> parse
        -> update snapshot
        -> repeat indefinitely

One persistent background thread per (bookmaker, LIVE/PREMATCH) feed --
never a new process/browser per poll. A plain `threading.Thread` is
sufficient here (unlike OnWin, which needs a separate process for its
Playwright sync API -- see collector.py) because every Kenyan
acquisition in this module is a simple stateless HTTP GET (`requests`),
not a long-lived browser session.

Last-good snapshot behavior: a failed or empty poll never immediately
blanks out previously-published valid opportunities. The most recent
successful (non-empty OR explicitly-confirmed-empty) result keeps being
served by `get_matches()` until it exceeds KENYAN_STALE_AFTER_SECONDS,
matching the project's own general stale-data policy (see
collector.py's MAX_ODDS_AGE_SECONDS) but as an independent constant so
nothing here can affect the existing bookmakers' staleness handling.
"""
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from kenyan.config import KENYAN_POLL_INTERVAL_SECONDS, KENYAN_STALE_AFTER_SECONDS
from kenyan.health import HealthState, WorkerHealth


@dataclass
class Diagnostics:
    """
    Isolated diagnostics record for one acquisition cycle -- see the
    task's "DIAGNOSTICS" requirement. Deliberately excludes anything
    resembling a credential/session token; these workers are plain
    unauthenticated HTTP GETs, so there is nothing sensitive to redact,
    but the shape is kept minimal on principle regardless.
    """

    endpoint_status: str = "unknown"  # "ok" | "http_error" | "bad_payload" | "exception"
    http_status_code: Optional[int] = None
    content_type: Optional[str] = None
    response_size_bytes: int = 0
    events_discovered: int = 0
    football_events: int = 0
    one_x_two_events: int = 0
    valid_normalized_events: int = 0
    parser_error: Optional[str] = None
    acquired_at: Optional[float] = None
    elapsed_seconds: float = 0.0


class BaseKenyanWorker:
    """
    `poll_fn` is a zero-argument callable that performs ONE full
    acquire -> parse -> normalize cycle and returns
    `(matches: list[KenyanMatchOdds], diagnostics: Diagnostics)`.
    It must not raise for ordinary, expected failure modes (HTTP
    errors, bad payloads) -- those should be reflected in the returned
    Diagnostics instead, so a single bad cycle degrades health rather
    than killing the worker thread. Only a truly unexpected exception
    should propagate, and even then this base class catches it so the
    thread itself never dies.
    """

    def __init__(
        self,
        name: str,
        poll_fn: Callable[[], "tuple"],
        *,
        poll_interval_seconds: float = KENYAN_POLL_INTERVAL_SECONDS,
    ):
        self.name = name
        self._poll_fn = poll_fn
        self._poll_interval_seconds = poll_interval_seconds

        self._lock = threading.Lock()
        self._matches = []
        self._last_good_at: Optional[float] = None
        self._last_attempt_at: Optional[float] = None
        self._last_diagnostics: Optional[Diagnostics] = None
        self._health_state = HealthState()

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"kenyan-{self.name}", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5):
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------

    def _run(self):
        while not self._stop_event.is_set():
            cycle_start = time.monotonic()
            self._run_one_cycle()
            elapsed = time.monotonic() - cycle_start
            self._stop_event.wait(max(0.0, self._poll_interval_seconds - elapsed))

    def _run_one_cycle(self):
        now = time.time()

        try:
            matches, diagnostics = self._poll_fn()
        except Exception as exc:  # noqa: BLE001 -- worker must never die
            with self._lock:
                self._last_attempt_at = now
                self._health_state.record_failure(f"{type(exc).__name__}: {exc}")
                self._last_diagnostics = Diagnostics(
                    endpoint_status="exception",
                    parser_error=f"{type(exc).__name__}: {exc}",
                    acquired_at=now,
                )
            return

        with self._lock:
            self._last_attempt_at = now
            self._last_diagnostics = diagnostics

            if diagnostics.endpoint_status == "ok" and diagnostics.parser_error is None:
                if matches:
                    self._matches = matches
                    self._last_good_at = now
                    self._health_state.record_success()
                else:
                    # Well-formed payload, genuinely zero relevant
                    # events right now (e.g. no live football matches
                    # this instant) -- not a failure. Snapshot is left
                    # as-is (last-good), health is untouched.
                    self._health_state.record_empty_but_ok()
            else:
                self._health_state.record_failure(
                    diagnostics.parser_error or f"endpoint_status={diagnostics.endpoint_status}"
                )

    # ------------------------------------------------------------
    # Readers (safe to call from any thread, cheap, no network/IO)
    # ------------------------------------------------------------

    def get_matches(self) -> list:
        """
        Last-good snapshot, gated purely on DATA staleness (age since
        the last successful acquisition vs KENYAN_STALE_AFTER_SECONDS)
        -- deliberately independent of the reported health's
        consecutive-failure hysteresis (see kenyan/health.py). This
        means a worker can be reported DEGRADED (e.g. after 3
        consecutive failed polls, ~15s) while STILL serving perfectly
        fresh matches from before those failures started, but once the
        snapshot itself is older than the staleness threshold it is
        dropped -- "use last-good snapshots, but don't keep stale
        opportunities indefinitely".
        """

        with self._lock:
            if self._last_good_at is None:
                return []
            if (time.time() - self._last_good_at) > KENYAN_STALE_AFTER_SECONDS:
                return []
            return list(self._matches)

    def get_status(self) -> dict:
        with self._lock:
            now = time.time()
            health = self._health_state.classify(last_good_at=self._last_good_at, now=now)
            age = (now - self._last_good_at) if self._last_good_at else None

            return {
                "name": self.name,
                "health": health.value,
                "last_good_at": self._last_good_at,
                "last_attempt_at": self._last_attempt_at,
                "age_seconds": age,
                "match_count": len(self._matches),
                "error": self._health_state.last_error,
                "diagnostics": _diagnostics_to_dict(self._last_diagnostics),
            }


def _diagnostics_to_dict(diagnostics: Optional[Diagnostics]) -> Optional[dict]:
    if diagnostics is None:
        return None
    return {
        "endpoint_status": diagnostics.endpoint_status,
        "http_status_code": diagnostics.http_status_code,
        "content_type": diagnostics.content_type,
        "response_size_bytes": diagnostics.response_size_bytes,
        "events_discovered": diagnostics.events_discovered,
        "football_events": diagnostics.football_events,
        "one_x_two_events": diagnostics.one_x_two_events,
        "valid_normalized_events": diagnostics.valid_normalized_events,
        "parser_error": diagnostics.parser_error,
        "acquired_at": diagnostics.acquired_at,
        "elapsed_seconds": diagnostics.elapsed_seconds,
    }
