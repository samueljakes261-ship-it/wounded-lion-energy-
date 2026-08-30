"""
Worker health state machine for the Kenyan Bookmakers module.

Deliberately a fresh, independent copy rather than an import of
engine/collector_health.py: that module's hysteresis constants are
tuned specifically for OnWin/BetKanyon/Orbit's own natural cycle times
(BetKanyon ~3s poll, OnWin/Orbit push-driven), and the task explicitly
asks that nothing about the existing workers' behavior be touched, so
this is intentionally a standalone module -- there is no shared state,
no shared import, and no way changing this file could ever affect the
existing feeds.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from kenyan.config import (
    KENYAN_DEGRADE_AFTER_CONSECUTIVE_FAILURES,
    KENYAN_RECOVER_AFTER_CONSECUTIVE_SUCCESSES,
    KENYAN_STALE_AFTER_SECONDS,
)


class WorkerHealth(str, Enum):
    """
    RUNNING means: a recent successful HTTP acquisition, a recent
    valid payload, AND the parser successfully produced valid
    normalized events. It does NOT just mean "the worker thread is
    alive".
    """

    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    STOPPED = "STOPPED"


@dataclass
class HealthState:
    """
    Tracks the rolling consecutive-failure/success counters used to
    decide a worker's reported health, with hysteresis so a single
    blip does not flip status back and forth.

    `is_degraded` is a sticky flag: once
    KENYAN_DEGRADE_AFTER_CONSECUTIVE_FAILURES consecutive failures trip
    it, it only clears after KENYAN_RECOVER_AFTER_CONSECUTIVE_SUCCESSES
    consecutive clean cycles in a row -- a single lucky retry sandwiched
    between failures does not flap the reported status back to RUNNING.
    """

    consecutive_failures: int = 0
    consecutive_successes: int = 0
    has_ever_succeeded: bool = False
    is_degraded: bool = False
    last_error: Optional[str] = None

    def record_success(self):
        self.consecutive_failures = 0
        self.consecutive_successes += 1
        self.has_ever_succeeded = True
        self.last_error = None

        if (
            self.is_degraded
            and self.consecutive_successes >= KENYAN_RECOVER_AFTER_CONSECUTIVE_SUCCESSES
        ):
            self.is_degraded = False

    def record_failure(self, error: str):
        self.consecutive_successes = 0
        self.consecutive_failures += 1
        self.last_error = error

        if self.consecutive_failures >= KENYAN_DEGRADE_AFTER_CONSECUTIVE_FAILURES:
            self.is_degraded = True

    def record_empty_but_ok(self):
        """
        A well-formed, successfully-fetched-and-parsed payload that
        just happens to contain zero currently-relevant events (e.g.
        no live football matches right now). This is NOT a failure --
        it should neither degrade nor "recover" the worker; it simply
        leaves the existing counters/flags untouched.
        """

    def classify(
        self,
        *,
        last_good_at: Optional[float],
        now: float,
        stale_after_seconds: float = KENYAN_STALE_AFTER_SECONDS,
    ) -> WorkerHealth:
        if not self.has_ever_succeeded:
            return WorkerHealth.STARTING

        if self.is_degraded:
            return WorkerHealth.DEGRADED

        if last_good_at is None or (now - last_good_at) > stale_after_seconds:
            return WorkerHealth.DEGRADED

        return WorkerHealth.RUNNING
