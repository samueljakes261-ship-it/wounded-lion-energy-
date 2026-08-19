"""
Deterministic tests for the persistent BetKanyon worker
(parsers/betkanyon/worker.py).

These tests never touch the network/browser: BetkanyonFeed is replaced
with a small fake that mimics its collect_once()/get_parsed_event_count()/
close() surface, with a fully controllable outcome per call. That lets
us verify the worker's *lifecycle* (single persistent feed reused across
polls, no overlapping polls, reconnect-on-failure, clean stop) rather
than the underlying acquisition mechanism (which is intentionally left
untouched -- see parsers/betkanyon/fetcher.py).
"""

import time
from datetime import datetime, timezone

import pytest

import parsers.betkanyon.worker as worker_module
from parsers.betkanyon.worker import BetkanyonWorker
from models.match import MatchOdds


def make_match(home="Home", away="Away"):
    now = datetime.now(timezone.utc)
    return MatchOdds(
        bookmaker="Betkanyon",
        competition="Test League",
        sport="football",
        market="Match Odds",
        home_team=home,
        away_team=away,
        home_odds=2.0,
        draw_odds=3.0,
        away_odds=4.0,
        start_time=now,
        collected_at=now,
    )


class FakeBetkanyonFeed:
    """
    Stand-in for parsers.betkanyon.feed.BetkanyonFeed.

    `script` is a dict of factory-level knobs (shared across every fake
    instance created during one test) so the test can script exactly
    what should happen without depending on real timing:

      - fail_first_instances: how many *feed instances* (not calls)
        should always raise on collect_once(), simulating a dead
        browser/session that needs a full reconnect.
      - fail_first_calls: how many collect_once() *calls* (across the
        current instance) should raise before succeeding, simulating
        a transient (non-connection) hiccup that should be retried in
        place without recreating the feed.
      - fail_message: the exception message raised by the above two
        knobs -- lets a test control whether it's classified as a
        dead-connection error or a generic transient one (see
        engine.collector_health.is_connection_dead_error).
      - call_delay: artificial time spent "processing" one cycle.
    """

    instances = []

    def __init__(self, script):
        self.script = script
        self.instance_index = len(FakeBetkanyonFeed.instances)
        FakeBetkanyonFeed.instances.append(self)

        self.call_count = 0
        self.closed = False
        self.in_call = False
        self.overlap_detected = False
        self._matches = []

    def collect_once(self):
        if self.in_call:
            self.overlap_detected = True
        self.in_call = True

        try:
            self.call_count += 1

            if self.instance_index < self.script.get("fail_first_instances", 0):
                factory = self.script.get("fail_factory")
                if factory is not None:
                    raise factory()
                raise RuntimeError(
                    self.script.get("fail_message", "simulated BetKanyon fetch failure")
                )

            if self.call_count <= self.script.get("fail_first_calls", 0):
                factory = self.script.get("fail_factory")
                if factory is not None:
                    raise factory()
                raise RuntimeError(
                    self.script.get("fail_message", "simulated BetKanyon fetch failure")
                )

            delay = self.script.get("call_delay", 0.0)
            if delay:
                time.sleep(delay)

            self._matches = [make_match()]
            return self._matches
        finally:
            self.in_call = False

    def get_parsed_event_count(self):
        return len(self._matches)

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def reset_fake_feed_registry():
    FakeBetkanyonFeed.instances = []
    yield
    FakeBetkanyonFeed.instances = []


def make_worker(monkeypatch, poll_interval, **script):
    factory = lambda: FakeBetkanyonFeed(script)  # noqa: E731
    monkeypatch.setattr(worker_module, "BetkanyonFeed", factory)
    return BetkanyonWorker(poll_interval=poll_interval)


def wait_until(predicate, timeout=3.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


# ----------------------------------------------------------------------
# Basic lifecycle / publication
# ----------------------------------------------------------------------

def test_worker_publishes_matches_after_first_successful_poll(monkeypatch):
    worker = make_worker(monkeypatch, poll_interval=0.05)
    worker.start()

    try:
        assert wait_until(lambda: len(worker.get_matches()) > 0)

        status = worker.get_status()
        assert status["status"] == "running"
        assert status["error"] is None
        assert status["last_update_at"] is not None
        assert status["success_count"] >= 1
        assert status["last_odds_count"] == 1
    finally:
        worker.stop()


def test_worker_reuses_single_persistent_feed_across_polls(monkeypatch):
    """The browser/session (fake feed) must be created ONCE and reused
    -- not recreated every poll cycle."""

    worker = make_worker(monkeypatch, poll_interval=0.03)
    worker.start()

    try:
        assert wait_until(lambda: worker.get_status()["success_count"] >= 5, timeout=3.0)
    finally:
        worker.stop()

    assert len(FakeBetkanyonFeed.instances) == 1


def test_worker_freshness_timestamp_advances_between_polls(monkeypatch):
    worker = make_worker(monkeypatch, poll_interval=0.03)
    worker.start()

    try:
        assert wait_until(lambda: worker.get_status()["success_count"] >= 1)
        first_update = worker.get_status()["last_update_at"]

        assert wait_until(
            lambda: worker.get_status()["last_update_at"] != first_update,
            timeout=3.0,
        )
        second_update = worker.get_status()["last_update_at"]

        assert second_update > first_update
    finally:
        worker.stop()


def test_worker_no_overlapping_polls_when_cycle_is_slow(monkeypatch):
    """If one cycle takes longer than poll_interval, the worker must
    start the next cycle immediately afterward -- never concurrently."""

    worker = make_worker(monkeypatch, poll_interval=0.01, call_delay=0.08)
    worker.start()

    try:
        # Let several (intentionally slow) cycles run.
        time.sleep(0.35)
    finally:
        worker.stop()

    assert len(FakeBetkanyonFeed.instances) == 1
    fake = FakeBetkanyonFeed.instances[0]
    assert fake.overlap_detected is False
    assert fake.call_count >= 2


# ----------------------------------------------------------------------
# Reconnection
# ----------------------------------------------------------------------

def test_worker_reconnects_after_feed_failure(monkeypatch):
    """First feed instance always fails with a dead-browser-style error
    -> worker must close it immediately, create a brand-new feed
    instance, and recover to a healthy state."""

    worker = BetkanyonWorker(poll_interval=0.02)
    script = {
        "fail_first_instances": 1,
        "fail_message": "Target page, context or browser has been closed",
    }
    monkeypatch.setattr(
        worker_module, "BetkanyonFeed", lambda: FakeBetkanyonFeed(script)
    )

    # Force a tiny reconnect backoff so the test doesn't need to wait
    # out the module's real (much larger) default backoff.
    monkeypatch.setattr(worker_module, "INITIAL_BACKOFF_SECONDS", 0.05)
    monkeypatch.setattr(worker_module, "MAX_BACKOFF_SECONDS", 0.05)

    worker.start()

    try:
        assert wait_until(
            lambda: worker.get_status()["status"] == "reconnecting",
            timeout=2.0,
        )
        assert wait_until(
            lambda: worker.get_status()["status"] == "running",
            timeout=6.0,
        )
    finally:
        worker.stop()

    assert len(FakeBetkanyonFeed.instances) == 2
    assert FakeBetkanyonFeed.instances[0].closed is True
    assert worker.get_status()["error"] is None


# ----------------------------------------------------------------------
# Resilience: transient (non-connection) failures retry IN PLACE
# instead of tearing down and recreating the whole browser session.
# ----------------------------------------------------------------------

def test_transient_failure_retries_in_place_without_reconnecting(monkeypatch):
    """
    A single decrypt/parse-style failure (NOT a browser/connection
    error) must be retried on the SAME feed instance -- no new
    BetkanyonFeed, no "reconnecting" status, no closed browser --
    exactly the LEVEL 1 escalation from the resilience spec.
    """
    monkeypatch.setattr(worker_module, "INPLACE_RETRY_PAUSE_SECONDS", 0.01)

    worker = BetkanyonWorker(poll_interval=0.02)
    script = {
        "fail_first_calls": 1,
        "fail_message": "malformed payload: could not decrypt",
    }
    monkeypatch.setattr(
        worker_module, "BetkanyonFeed", lambda: FakeBetkanyonFeed(script)
    )

    worker.start()

    try:
        assert wait_until(lambda: worker.get_status()["success_count"] >= 1, timeout=3.0)

        # Checked BEFORE stop() (which always closes the feed as part
        # of a clean shutdown) -- what matters here is that the feed
        # was never closed WHILE recovering from the transient error.
        assert len(FakeBetkanyonFeed.instances) == 1
        assert FakeBetkanyonFeed.instances[0].closed is False
        status = worker.get_status()
        assert status["reconnect_count"] == 0
        assert status["failed_count"] >= 1
    finally:
        worker.stop()


def test_persistent_transient_failures_eventually_force_reconnect(monkeypatch):
    """
    Bounded safety net: even an exception NOT recognized as a
    connection-dead signal must eventually force a real reconnect if
    it keeps recurring on the same feed instance -- a worker must
    never retry forever against a session that never actually
    recovers.
    """
    monkeypatch.setattr(worker_module, "INPLACE_RETRY_PAUSE_SECONDS", 0.01)
    monkeypatch.setattr(worker_module, "INITIAL_BACKOFF_SECONDS", 0.02)
    monkeypatch.setattr(worker_module, "MAX_BACKOFF_SECONDS", 0.02)

    worker = BetkanyonWorker(poll_interval=0.02)
    script = {
        "fail_first_instances": 1,
        "fail_message": "unexpected KeyError in parser",
    }
    monkeypatch.setattr(
        worker_module, "BetkanyonFeed", lambda: FakeBetkanyonFeed(script)
    )

    worker.start()

    try:
        assert wait_until(
            lambda: worker.get_status()["status"] == "running", timeout=5.0
        )
    finally:
        worker.stop()

    assert len(FakeBetkanyonFeed.instances) == 2
    assert FakeBetkanyonFeed.instances[0].closed is True
    assert worker.get_status()["reconnect_count"] >= 1


# ----------------------------------------------------------------------
# Shutdown
# ----------------------------------------------------------------------

def test_worker_stop_closes_feed_and_stops_thread(monkeypatch):
    worker = make_worker(monkeypatch, poll_interval=0.03)
    worker.start()

    assert wait_until(lambda: len(FakeBetkanyonFeed.instances) == 1)
    assert wait_until(lambda: worker.get_status()["success_count"] >= 1)

    worker.stop(timeout=5)

    assert worker.get_status()["status"] == "stopped"
    assert FakeBetkanyonFeed.instances[0].closed is True
    assert worker._thread.is_alive() is False


def test_worker_start_is_idempotent(monkeypatch):
    """Calling start() twice must not spin up a second polling thread
    (which would mean two feeds / duplicate browsers)."""

    worker = make_worker(monkeypatch, poll_interval=0.05)
    worker.start()
    first_thread = worker._thread

    worker.start()
    second_thread = worker._thread

    assert first_thread is second_thread

    worker.stop()


def test_worker_waits_on_credential_cooldown_then_recovers(monkeypatch):
    """AllCredentialsUnavailableError must wait retry_after instead of
    spinning in-place 1s retries, then resume on a fresh feed."""
    from credentials.errors import AllCredentialsUnavailableError

    worker = make_worker(
        monkeypatch,
        poll_interval=0.02,
        fail_first_instances=1,
        fail_factory=lambda: AllCredentialsUnavailableError(
            "cooling down", retry_after_seconds=0.05,
        ),
    )
    monkeypatch.setattr(worker_module, "INITIAL_BACKOFF_SECONDS", 0.05)
    monkeypatch.setattr(worker_module, "MAX_BACKOFF_SECONDS", 0.05)

    started = time.monotonic()
    worker.start()
    try:
        assert wait_until(
            lambda: worker.get_status()["status"] == "running",
            timeout=3.0,
        )
    finally:
        worker.stop()

    elapsed = time.monotonic() - started
    assert elapsed < 2.0
    assert len(FakeBetkanyonFeed.instances) == 2
    assert FakeBetkanyonFeed.instances[0].closed is True
    assert worker.get_status()["error"] is None
