"""
Long-running simulation (spec section 17): drives the REAL
BetkanyonWorker through many collection cycles under a realistic mix
of occasional transient hiccups, rarer genuine connection drops, and
otherwise-normal operation, and verifies the collector spends the
VAST MAJORITY of its time reporting RUNNING/RECOVERING rather than
oscillating RUNNING -> DEGRADED -> RUNNING -> DEGRADED on every blip.

This is an integration-level test across three pieces working
together: the worker's consecutive-failure/success counters (LEVEL
1/2 escalation, see engine/collector_health.py), and collector.py's
hysteresis-based _classify_collector_status(). No network/browser is
used -- BetkanyonFeed is replaced with a scripted, seeded-random fake.
"""

import random
import threading
import time

import collector
from parsers.betkanyon.worker import BetkanyonWorker
import parsers.betkanyon.worker as worker_module
from models.match import MatchOdds


TRANSIENT_FAILURE_RATE = 0.12
DEAD_CONNECTION_FAILURE_RATE = 0.02

SIMULATION_CYCLES = 300


def make_match():
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return MatchOdds(
        bookmaker="Betkanyon", competition="Test League", sport="football",
        market="Match Odds", home_team="Home", away_team="Away",
        home_odds=2.0, draw_odds=3.0, away_odds=4.0,
        start_time=now, collected_at=now,
    )


class SimulatedFeed:
    """
    A single collect_once() call randomly (but deterministically, via
    a seeded RNG shared across every instance created during the run)
    behaves as:
      - a transient, non-connection hiccup (should be retried in
        place -- see engine.collector_health.is_connection_dead_error)
      - a genuine dead-connection error (should force a real reconnect)
      - a normal success

    Deliberately mimics realistic bookmaker behavior: MOSTLY healthy,
    occasionally flaky, rarely actually disconnected -- not a
    permanently broken feed.
    """

    rng = random.Random(1234)
    call_count = 0
    close_count = 0

    def __init__(self):
        pass

    def collect_once(self):
        SimulatedFeed.call_count += 1
        roll = SimulatedFeed.rng.random()

        if roll < DEAD_CONNECTION_FAILURE_RATE:
            raise RuntimeError("Target page, context or browser has been closed")

        if roll < DEAD_CONNECTION_FAILURE_RATE + TRANSIENT_FAILURE_RATE:
            # Deliberately does NOT contain any dead-connection marker
            # (see engine.collector_health) -- this represents a pure
            # parse/decrypt-style hiccup, not a transport failure.
            raise RuntimeError("simulated malformed payload from parser")

        return [make_match()]

    def get_parsed_event_count(self):
        return 1

    def close(self):
        SimulatedFeed.close_count += 1


def test_collector_spends_most_of_the_simulation_running_not_oscillating(monkeypatch):
    SimulatedFeed.call_count = 0
    SimulatedFeed.close_count = 0

    monkeypatch.setattr(worker_module, "BetkanyonFeed", SimulatedFeed)
    monkeypatch.setattr(worker_module, "INPLACE_RETRY_PAUSE_SECONDS", 0.002)
    monkeypatch.setattr(worker_module, "INITIAL_BACKOFF_SECONDS", 0.01)
    monkeypatch.setattr(worker_module, "MAX_BACKOFF_SECONDS", 0.02)

    worker = BetkanyonWorker(poll_interval=0.005)
    worker.start()

    samples = []

    try:
        deadline = time.monotonic() + 8.0

        while SimulatedFeed.call_count < SIMULATION_CYCLES and time.monotonic() < deadline:
            status = worker.get_status()

            last_update_at = status.get("last_update_at")
            age = (time.time() - last_update_at) if last_update_at else None

            classification = collector._classify_collector_status(
                status.get("status"),
                age,
                True,
                consecutive_failures=status.get("consecutive_failures", 0),
                consecutive_successes=status.get("consecutive_successes", 0),
                reconnect_count=status.get("reconnect_count", 0),
            )
            samples.append(classification)

            time.sleep(0.005)
    finally:
        worker.stop()

    assert SimulatedFeed.call_count >= SIMULATION_CYCLES, (
        "simulation did not run enough cycles to be statistically meaningful"
    )
    assert len(samples) > 20

    degraded_count = sum(1 for s in samples if s == collector.CollectorStatus.DEGRADED.value)
    degraded_fraction = degraded_count / len(samples)

    # With only ~12% transient + ~2% dead-connection failures per
    # cycle -- neither remotely a "persistent provider failure" -- the
    # hysteresis-based classifier must keep the collector reporting
    # DEGRADED only rarely, not on every blip.
    assert degraded_fraction < 0.15, (
        f"collector spent {degraded_fraction:.0%} of the simulation DEGRADED "
        f"under a mild, mostly-transient failure rate -- hysteresis is not "
        f"working as intended"
    )

    # No unbounded degradation: the worker must always find its way
    # back to a healthy status, never getting permanently stuck.
    healthy_values = {
        collector.CollectorStatus.RUNNING.value,
        collector.CollectorStatus.RECOVERING.value,
    }
    assert any(s in healthy_values for s in samples[-10:]), (
        "collector ended the simulation in a persistently unhealthy state"
    )


def test_transient_failure_rate_does_not_cause_reconnect_storm(monkeypatch):
    """
    A meaningfully lower reconnect count than failure count proves
    transient failures are mostly being absorbed via in-place retry
    (LEVEL 1) rather than tearing down and recreating the browser
    session (LEVEL 2/3) for every single blip.
    """
    SimulatedFeed.call_count = 0
    SimulatedFeed.close_count = 0

    monkeypatch.setattr(worker_module, "BetkanyonFeed", SimulatedFeed)
    monkeypatch.setattr(worker_module, "INPLACE_RETRY_PAUSE_SECONDS", 0.002)
    monkeypatch.setattr(worker_module, "INITIAL_BACKOFF_SECONDS", 0.01)
    monkeypatch.setattr(worker_module, "MAX_BACKOFF_SECONDS", 0.02)

    worker = BetkanyonWorker(poll_interval=0.005)
    worker.start()

    deadline = time.monotonic() + 8.0
    while SimulatedFeed.call_count < SIMULATION_CYCLES and time.monotonic() < deadline:
        time.sleep(0.01)

    status = worker.get_status()
    worker.stop()

    assert SimulatedFeed.call_count >= SIMULATION_CYCLES

    failed_count = status.get("failed_count", 0)
    reconnect_count = status.get("reconnect_count", 0)

    assert failed_count > 0
    # Every dead-connection failure and every 3rd consecutive transient
    # failure forces a reconnect -- but with only ~12% transient +
    # ~2% dead failures, the vast majority of transient failures
    # should resolve via in-place retry well before hitting that
    # bound, so reconnects should be a small fraction of failures.
    assert reconnect_count < failed_count * 0.5, (
        f"reconnected {reconnect_count} times out of {failed_count} failures -- "
        f"too many full session teardowns for a mostly-transient failure rate"
    )
