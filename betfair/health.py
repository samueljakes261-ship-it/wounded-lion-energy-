"""
Health state machine for the Betfair valuebets worker.

Standalone copy of the Kenyan hysteresis idea (STARTING / RUNNING /
DEGRADED) so this feed cannot change Kenyan or Turkish collector health.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from betfair.config import (
    DEGRADE_AFTER_CONSECUTIVE_FAILURES,
    RECOVER_AFTER_CONSECUTIVE_SUCCESSES,
    STALE_AFTER_SECONDS,
)


class WorkerHealth(str, Enum):
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    STOPPED = "STOPPED"


def _is_missing_credentials(error: Optional[str]) -> bool:
    if not error:
        return False
    return "not set" in error


@dataclass
class HealthState:
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
            and self.consecutive_successes >= RECOVER_AFTER_CONSECUTIVE_SUCCESSES
        ):
            self.is_degraded = False

    def record_failure(self, error: str):
        self.consecutive_successes = 0
        self.consecutive_failures += 1
        self.last_error = error
        if self.consecutive_failures >= DEGRADE_AFTER_CONSECUTIVE_FAILURES:
            self.is_degraded = True
        if _is_missing_credentials(error):
            self.is_degraded = True

    def classify(
        self,
        *,
        last_good_at: Optional[float],
        now: float,
        stale_after_seconds: float = STALE_AFTER_SECONDS,
    ) -> WorkerHealth:
        if _is_missing_credentials(self.last_error):
            return WorkerHealth.FAILED
        # Persistent failure is DEGRADED even before the first success
        # so a broken login is not stuck on STARTING forever.
        if self.is_degraded:
            return WorkerHealth.DEGRADED
        if not self.has_ever_succeeded:
            return WorkerHealth.STARTING
        if last_good_at is None or (now - last_good_at) > stale_after_seconds:
            return WorkerHealth.DEGRADED
        return WorkerHealth.RUNNING
