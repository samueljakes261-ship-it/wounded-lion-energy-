"""
Unit tests for collector.py's canonical collector-health classifier
(_classify_collector_status / CollectorStatus).

Issue 2: "0 opportunities" must NEVER be interpreted as "the collector
stopped" -- this classifier takes NO opportunity-derived input at all
(only a worker's own raw status string, its own age-since-last-publish,
whether its process/thread/task is alive, and its consecutive
failure/success/reconnect counters), which is what makes that
guarantee structural rather than incidental.

LONG-RUNNING STABILITY: this classifier also implements HYSTERESIS
(see engine/collector_health.py) so that a single transient failure --
even one that puts a worker into "reconnecting" -- does NOT immediately
read as DEGRADED as long as the underlying data is still safely fresh.
DEGRADED must only ever mean "this data is no longer trustworthy",
never "one request happened to fail a moment ago".
"""

import collector
from collector import CollectorStatus, _classify_collector_status
from engine.collector_health import (
    DEGRADE_AFTER_CONSECUTIVE_FAILURES,
    RECOVER_AFTER_CONSECUTIVE_SUCCESSES,
)


MAX_AGE = collector.MAX_ODDS_AGE_SECONDS


# ----------------------------------------------------------------------
# Basic states (no failures/successes involved)
# ----------------------------------------------------------------------

def test_running_and_fresh_is_running():
    assert _classify_collector_status("running", 1.0, True) == CollectorStatus.RUNNING.value


def test_starting_raw_status_is_starting():
    assert _classify_collector_status("starting", None, True) == CollectorStatus.STARTING.value


def test_alive_but_never_published_is_starting_not_error():
    assert _classify_collector_status("running", None, True) == CollectorStatus.STARTING.value


def test_explicit_stopped_status_is_stopped():
    assert _classify_collector_status("stopped", None, True) == CollectorStatus.STOPPED.value


def test_dead_process_with_stopped_status_is_stopped():
    assert _classify_collector_status("stopped", None, False) == CollectorStatus.STOPPED.value


def test_dead_process_with_non_stopped_status_is_error():
    """A process/thread/task that died WITHOUT an intentional stop()
    call is a real failure, distinguishable from a graceful stop and
    from "just no opportunities right now"."""
    assert _classify_collector_status("running", 1.0, False) == CollectorStatus.ERROR.value


def test_classification_never_depends_on_opportunity_count():
    """
    Structural guarantee: the function signature itself takes no
    opportunity/arbitrage argument, so a healthy, actively-collecting
    worker classifies identically regardless of how many (if any)
    arbitrage opportunities currently exist elsewhere in the engine.
    """
    import inspect

    params = inspect.signature(_classify_collector_status).parameters
    assert "opportunity" not in "".join(params).lower()
    assert "arbitrage" not in "".join(params).lower()

    # And, functionally: RUNNING with fresh data is RUNNING, full stop.
    assert _classify_collector_status("running", 0.5, True) == CollectorStatus.RUNNING.value


# ----------------------------------------------------------------------
# Data-safety floor: staleness always wins, regardless of hysteresis.
# ----------------------------------------------------------------------

def test_running_but_old_age_is_degraded():
    assert (
        _classify_collector_status("running", MAX_AGE + 5, True)
        == CollectorStatus.DEGRADED.value
    )


def test_stale_age_is_degraded_even_with_zero_consecutive_failures():
    """The system must NEVER use stale odds indefinitely: even a
    worker with a spotless failure record is DEGRADED the moment its
    published data crosses the safety threshold."""
    assert (
        _classify_collector_status(
            "running", MAX_AGE + 1, True,
            consecutive_failures=0, consecutive_successes=50,
        )
        == CollectorStatus.DEGRADED.value
    )


# ----------------------------------------------------------------------
# Hysteresis: a single transient blip must NOT immediately degrade a
# collector whose last-known-good data is still safely fresh.
# ----------------------------------------------------------------------

def test_single_failure_with_fresh_data_is_not_degraded():
    """
    Core regression this refactor exists to fix: RUNNING -> single
    timeout -> retry -> success -> RUNNING, NOT RUNNING -> single
    timeout -> DEGRADED -> opportunities disappear.
    """
    status = _classify_collector_status(
        "reconnecting", 2.0, True,
        consecutive_failures=1,
    )
    assert status != CollectorStatus.DEGRADED.value


def test_failures_below_threshold_with_fresh_data_stay_healthy():
    status = _classify_collector_status(
        "connecting", 1.0, True,
        consecutive_failures=DEGRADE_AFTER_CONSECUTIVE_FAILURES - 1,
    )
    assert status != CollectorStatus.DEGRADED.value


def test_consecutive_failures_reaching_threshold_is_degraded():
    """Enough failures IN A ROW is a real, sustained problem and must
    degrade even while the last publish is still technically within
    the freshness window."""
    status = _classify_collector_status(
        "reconnecting", 5.0, True,
        consecutive_failures=DEGRADE_AFTER_CONSECUTIVE_FAILURES,
    )
    assert status == CollectorStatus.DEGRADED.value


def test_reconnecting_with_no_prior_success_and_sustained_failures_is_degraded():
    """
    Real-world regression: a worker stuck retrying forever (e.g. every
    ZenRows credential in cooldown) reports "reconnecting" and may
    never have had a single successful publish (age stays None). Once
    its consecutive failures reach the sustained-failure threshold,
    this must show DEGRADED, not be mistaken for "still starting up".
    """
    assert (
        _classify_collector_status(
            "reconnecting", None, True,
            consecutive_failures=DEGRADE_AFTER_CONSECUTIVE_FAILURES,
        )
        == CollectorStatus.DEGRADED.value
    )


def test_reconnecting_with_no_prior_success_and_low_failures_is_starting():
    """A worker that has failed only once or twice while never having
    published yet is still plausibly just coming up -- not yet a
    confirmed sustained failure."""
    assert (
        _classify_collector_status(
            "reconnecting", None, True,
            consecutive_failures=1,
        )
        == CollectorStatus.STARTING.value
    )


# ----------------------------------------------------------------------
# Recovery: RECOVERING vs RUNNING after a reconnect.
# ----------------------------------------------------------------------

def test_recovering_after_reconnect_before_enough_successes():
    status = _classify_collector_status(
        "running", 1.0, True,
        consecutive_failures=0,
        consecutive_successes=RECOVER_AFTER_CONSECUTIVE_SUCCESSES - 1,
        reconnect_count=1,
    )
    assert status == CollectorStatus.RECOVERING.value


def test_running_once_enough_consecutive_successes_after_reconnect():
    status = _classify_collector_status(
        "running", 1.0, True,
        consecutive_failures=0,
        consecutive_successes=RECOVER_AFTER_CONSECUTIVE_SUCCESSES,
        reconnect_count=1,
    )
    assert status == CollectorStatus.RUNNING.value


def test_never_reconnected_worker_is_running_not_recovering():
    """A worker that has NEVER had to reconnect must never show
    RECOVERING just because its consecutive_successes counter happens
    to still be small (e.g. right after starting up cleanly)."""
    status = _classify_collector_status(
        "running", 1.0, True,
        consecutive_failures=0,
        consecutive_successes=1,
        reconnect_count=0,
    )
    assert status == CollectorStatus.RUNNING.value
