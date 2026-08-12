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
                raise RuntimeError("simulated BetKanyon fetch failure")

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
    """First feed instance always fails -> worker must close it, create
    a brand-new feed instance, and recover to a healthy state."""

    worker = BetkanyonWorker(poll_interval=0.02)
    script = {"fail_first_instances": 1}
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
