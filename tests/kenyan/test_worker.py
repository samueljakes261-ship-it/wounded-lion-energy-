"""
Tests for kenyan/workers/base.py's persistent worker loop: polling
cadence, last-good snapshot behavior, and health transitions --
entirely with a fake `poll_fn`, no real network access.
"""
import time

from kenyan.health import WorkerHealth
from kenyan.models import KenyanMatchOdds
from kenyan.workers.base import BaseKenyanWorker, Diagnostics


def _match(bookmaker="Test"):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return KenyanMatchOdds(
        bookmaker=bookmaker,
        competition="X",
        sport="Football",
        market="1X2",
        home_team="A",
        away_team="B",
        home_odds=2.0,
        draw_odds=3.0,
        away_odds=4.0,
        start_time=now,
        collected_at=now,
    )


def _ok_diagnostics(**overrides):
    defaults = dict(endpoint_status="ok", acquired_at=time.time())
    defaults.update(overrides)
    return Diagnostics(**defaults)


def test_worker_polls_at_configured_interval():
    call_count = {"n": 0}

    def poll_fn():
        call_count["n"] += 1
        return [_match()], _ok_diagnostics()

    worker = BaseKenyanWorker("test", poll_fn, poll_interval_seconds=0.05)
    worker.start()
    try:
        time.sleep(0.35)
        # ~0.35s / 0.05s interval => roughly 6-7 cycles; assert a
        # reasonable range rather than an exact count to avoid flaky
        # timing assumptions.
        assert 4 <= call_count["n"] <= 12
    finally:
        worker.stop()


def test_worker_reports_starting_before_first_success():
    def poll_fn():
        return [], _ok_diagnostics()

    worker = BaseKenyanWorker("test", poll_fn, poll_interval_seconds=10)
    status = worker.get_status()
    assert status["health"] == WorkerHealth.STARTING.value
    assert worker.get_matches() == []


def test_worker_reports_running_after_successful_poll_with_matches():
    def poll_fn():
        return [_match()], _ok_diagnostics(valid_normalized_events=1)

    worker = BaseKenyanWorker("test", poll_fn, poll_interval_seconds=0.05)
    worker.start()
    try:
        _wait_until(lambda: worker.get_status()["health"] == WorkerHealth.RUNNING.value)
        assert len(worker.get_matches()) == 1
    finally:
        worker.stop()


def test_last_good_snapshot_survives_a_temporary_http_failure():
    """
    A single failed poll must NOT immediately blank out previously
    published valid opportunities -- the last-good snapshot keeps
    being served.
    """
    state = {"fail": False}

    def poll_fn():
        if state["fail"]:
            raise ConnectionError("simulated transient network failure")
        return [_match()], _ok_diagnostics(valid_normalized_events=1)

    worker = BaseKenyanWorker("test", poll_fn, poll_interval_seconds=0.05)
    worker.start()
    try:
        _wait_until(lambda: len(worker.get_matches()) == 1)

        state["fail"] = True
        time.sleep(0.15)  # a couple of failed cycles

        # Snapshot is still served (well within the staleness window).
        assert len(worker.get_matches()) == 1
    finally:
        worker.stop()


def test_worker_recovers_after_failure():
    """
    STARTING (never succeeded) is a distinct state from DEGRADED
    (succeeded before, then started failing) -- this test drives the
    worker through a real success first, so subsequent failures are
    unambiguously a degrade-then-recover transition rather than
    "still starting".
    """
    state = {"mode": "ok"}

    def poll_fn():
        if state["mode"] == "fail":
            raise ConnectionError("simulated failure")
        return [_match()], _ok_diagnostics(valid_normalized_events=1)

    worker = BaseKenyanWorker("test", poll_fn, poll_interval_seconds=0.03)
    worker.start()
    try:
        _wait_until(lambda: worker.get_status()["health"] == WorkerHealth.RUNNING.value)

        state["mode"] = "fail"
        _wait_until(
            lambda: worker.get_status()["health"] == WorkerHealth.DEGRADED.value,
            timeout=2.0,
        )

        state["mode"] = "ok"
        _wait_until(
            lambda: worker.get_status()["health"] == WorkerHealth.RUNNING.value,
            timeout=2.0,
        )
        assert len(worker.get_matches()) == 1
    finally:
        worker.stop()


def test_empty_but_well_formed_payload_is_not_a_failure():
    """
    A well-formed response with genuinely zero current events (e.g.
    no live matches right now) must not degrade the worker.
    """

    def poll_fn():
        return [], _ok_diagnostics(events_discovered=0)

    worker = BaseKenyanWorker("test", poll_fn, poll_interval_seconds=0.03)
    worker.start()
    try:
        time.sleep(0.2)
        status = worker.get_status()
        # Never succeeded with actual matches, but never failed either
        # -- still STARTING (has_ever_succeeded requires a `matches`
        # success), and definitely not DEGRADED.
        assert status["health"] != WorkerHealth.DEGRADED.value
    finally:
        worker.stop()


def test_malformed_payload_is_reported_as_bad_payload_not_a_crash():
    def poll_fn():
        return [], Diagnostics(
            endpoint_status="bad_payload",
            parser_error="ValueError: could not parse",
            acquired_at=time.time(),
        )

    worker = BaseKenyanWorker("test", poll_fn, poll_interval_seconds=0.03)
    worker.start()
    try:
        time.sleep(0.15)
        status = worker.get_status()
        assert status["error"] is not None
        assert worker.is_alive()  # never crashed
    finally:
        worker.stop()


def test_worker_never_dies_on_unexpected_exception_in_poll_fn():
    def poll_fn():
        raise RuntimeError("totally unexpected bug")

    worker = BaseKenyanWorker("test", poll_fn, poll_interval_seconds=0.03)
    worker.start()
    try:
        time.sleep(0.15)
        assert worker.is_alive()
        status = worker.get_status()
        assert "totally unexpected bug" in (status["error"] or "")
    finally:
        worker.stop()


def _wait_until(predicate, timeout=1.0, interval=0.01):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s")
