"""
Deterministic tests for the persistent OnWin worker
(collector.py's _onwin_worker_main).

No network/browser: OnwinFeed is replaced with a small fake that mimics
its is_alive()/start()/poll()/close()/state surface, with fully
controllable outcomes per call. Runs the real worker function on a
background thread (it's a plain, synchronous, infinite loop -- exactly
what OnwinWorkerHandle also does via multiprocessing, but a thread
with a plain dict + threading.Event is enough to drive it
deterministically here) so this proves the worker's LEVEL 1/2
escalation policy (retry in place vs. full reconnect -- see
engine/collector_health.py) without any real ZenRows/Playwright
activity.
"""

import threading
import time

import pytest

import collector
from engine.collector_health import MAX_INPLACE_RETRIES


class FakeOnwinState:
    def __init__(self):
        self.event_count = 1

    def get_match_odds(self):
        return []


class FakeOnwinFeed:
    """
    script keys:
      fail_first_instances: how many *feed instances* should always
        fail on poll() (simulating a dead browser/page that needs a
        full reconnect).
      fail_first_calls: how many poll() *calls* (across the CURRENT
        instance) should fail before succeeding, simulating a
        transient hiccup that should be retried in place.
      fail_message: exception message used by the two knobs above.
    """

    instances = []
    script = {}

    def __init__(self):
        self.instance_index = len(FakeOnwinFeed.instances)
        FakeOnwinFeed.instances.append(self)
        self.state = FakeOnwinState()
        self.poll_count = 0
        self.closed = False
        self._alive = True

    def start(self, on_change=None, on_update=None, on_progress=None, timeout=180):
        if on_progress is not None:
            on_progress("waiting_main_line")
        return self.state

    def poll(self, tick_ms=500):
        self.poll_count += 1
        script = FakeOnwinFeed.script

        if self.instance_index < script.get("fail_first_instances", 0):
            raise RuntimeError(script.get("fail_message", "simulated OnWin failure"))

        if self.poll_count <= script.get("fail_first_calls", 0):
            raise RuntimeError(script.get("fail_message", "malformed update payload"))

    def is_alive(self):
        return self._alive

    def seconds_since_last_update(self):
        return FakeOnwinFeed.script.get("silent_for")

    def close(self):
        self.closed = True
        self._alive = False


@pytest.fixture(autouse=True)
def reset_fake_feed_registry():
    FakeOnwinFeed.instances = []
    FakeOnwinFeed.script = {}
    yield
    FakeOnwinFeed.instances = []
    FakeOnwinFeed.script = {}


def make_shared_state():
    return {
        "matches": [],
        "event_count": 0,
        "status": "starting",
        "error": None,
        "last_update_at": None,
        "last_attempt_at": None,
        "consecutive_failures": 0,
        "consecutive_successes": 0,
        "reconnect_count": 0,
        "request_count": 0,
        "success_count": 0,
        "failed_count": 0,
    }


def start_worker(monkeypatch, script):
    FakeOnwinFeed.script = script
    monkeypatch.setattr(collector, "OnwinFeed", FakeOnwinFeed)

    shared_state = make_shared_state()
    stop_event = threading.Event()

    thread = threading.Thread(
        target=collector._onwin_worker_main,
        args=(shared_state, stop_event),
        daemon=True,
    )
    thread.start()

    return shared_state, stop_event, thread


def wait_until(predicate, timeout=3.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def stop_worker(stop_event, thread, timeout=5):
    stop_event.set()
    thread.join(timeout=timeout)


def test_transient_poll_failure_retries_in_place_without_reconnecting(monkeypatch):
    """
    A single non-connection-style poll() failure must be retried on
    the SAME feed instance -- no new OnwinFeed, no reconnect count
    bump, no closed browser.
    """
    monkeypatch.setattr(collector, "INPLACE_RETRY_PAUSE_SECONDS", 0.01)

    shared_state, stop_event, thread = start_worker(
        monkeypatch,
        {"fail_first_calls": 1, "fail_message": "transient parse hiccup"},
    )

    try:
        assert wait_until(lambda: shared_state.get("success_count", 0) >= 1, timeout=3.0)

        assert len(FakeOnwinFeed.instances) == 1
        assert FakeOnwinFeed.instances[0].closed is False
        assert shared_state["reconnect_count"] == 0
        assert shared_state["failed_count"] >= 1
    finally:
        stop_worker(stop_event, thread)


def test_persistent_transient_poll_failures_eventually_force_reconnect(monkeypatch):
    """Bounded safety net: a non-connection-style error that keeps
    recurring on the same feed must still eventually force a real
    reconnect."""
    monkeypatch.setattr(collector, "INPLACE_RETRY_PAUSE_SECONDS", 0.01)
    monkeypatch.setattr(collector, "ONWIN_INITIAL_BACKOFF_SECONDS", 0.02)
    monkeypatch.setattr(collector, "ONWIN_MAX_BACKOFF_SECONDS", 0.02)

    shared_state, stop_event, thread = start_worker(
        monkeypatch,
        {"fail_first_instances": 1, "fail_message": "unexpected parser bug"},
    )

    try:
        # NOTE: "status" flips to "running" immediately after ANY
        # successful connect -- including the very first one, before
        # poll() has even been attempted once -- so waiting on status
        # alone would pass trivially without ever exercising the
        # retry-then-reconnect path this test targets. Waiting for a
        # SECOND feed instance to exist is the actual proof a
        # reconnect happened.
        assert wait_until(lambda: len(FakeOnwinFeed.instances) >= 2, timeout=10.0)
        assert wait_until(lambda: shared_state.get("status") == "running", timeout=5.0)
    finally:
        stop_worker(stop_event, thread)

    assert len(FakeOnwinFeed.instances) == 2
    assert FakeOnwinFeed.instances[0].closed is True
    assert shared_state["reconnect_count"] >= 1


def test_connection_dead_error_reconnects_immediately(monkeypatch):
    """A recognized dead-connection signal (e.g. a closed browser page)
    must force a reconnect on the very FIRST failure, without waiting
    for MAX_INPLACE_RETRIES consecutive failures."""
    monkeypatch.setattr(collector, "INPLACE_RETRY_PAUSE_SECONDS", 0.01)
    monkeypatch.setattr(collector, "ONWIN_INITIAL_BACKOFF_SECONDS", 0.02)
    monkeypatch.setattr(collector, "ONWIN_MAX_BACKOFF_SECONDS", 0.02)

    shared_state, stop_event, thread = start_worker(
        monkeypatch,
        {
            "fail_first_instances": 1,
            "fail_message": "Target page, context or browser has been closed",
        },
    )

    try:
        assert wait_until(lambda: shared_state.get("status") == "running", timeout=5.0)
    finally:
        stop_worker(stop_event, thread)

    assert len(FakeOnwinFeed.instances) == 2
    # Only ONE failed poll on instance 0 -- far fewer than
    # MAX_INPLACE_RETRIES -- was enough to trigger the reconnect.
    assert FakeOnwinFeed.instances[0].poll_count < MAX_INPLACE_RETRIES + 1
    assert shared_state["reconnect_count"] >= 1


def test_silent_update_feed_forces_reconnect(monkeypatch):
    """
    poll() succeeding with a page that has gone quiet must not leave
    OnWin permanently RUNNING on frozen odds -- a silent update feed
    past MAX_ODDS_AGE_SECONDS is treated as a dead connection.
    """
    monkeypatch.setattr(collector, "MAX_ODDS_AGE_SECONDS", 1.0)
    monkeypatch.setattr(collector, "ONWIN_INITIAL_BACKOFF_SECONDS", 0.01)
    monkeypatch.setattr(collector, "ONWIN_MAX_BACKOFF_SECONDS", 0.02)

    shared_state, stop_event, thread = start_worker(
        monkeypatch,
        {"silent_for": 5.0},
    )

    try:
        assert wait_until(lambda: len(FakeOnwinFeed.instances) >= 2, timeout=5.0)
        assert wait_until(lambda: shared_state.get("reconnect_count", 0) >= 1, timeout=3.0)
    finally:
        stop_worker(stop_event, thread)
