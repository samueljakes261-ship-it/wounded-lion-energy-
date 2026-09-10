"""
Deterministic tests for the persistent Orbit worker
(parsers/orbit/worker.py).

No network -- OrbitFeed is replaced with a small fake that mimics its
connect_and_subscribe()/receive_next()/get_match_odds()/close() surface,
with fully controllable outcomes per call. This proves the worker's
*lifecycle* (single persistent feed reused across frames, reconnect on
failure, clean stop, independent operation) rather than the real
REST/WebSocket protocol (left untouched -- see parsers/orbit/client.py).
"""

import asyncio
from datetime import datetime, timezone

import pytest

import parsers.orbit.worker as worker_module
from models.match import MatchOdds
from parsers.orbit.worker import OrbitWorker


@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_match(bookmaker="Orbit", side="BACK"):
    now = datetime.now(timezone.utc)
    return MatchOdds(
        bookmaker=bookmaker,
        competition="Test League",
        sport="football",
        market="Match Odds",
        home_team="Home FC",
        away_team="Away FC",
        home_odds=2.0,
        draw_odds=3.0,
        away_odds=4.0,
        start_time=now,
        collected_at=now,
        side=side,
    )


class FakeOrbitFeed:
    """
    script keys:
      fail_first_instances: how many feed instances always raise on
        connect_and_subscribe() (simulating a dead session needing a
        full reconnect).
      fail_receive_after: raise on receive_next() after this many
        successful frames on this instance (simulates a mid-session
        drop).
    """

    instances = []

    def __init__(self, script):
        self.script = script
        self.instance_index = len(FakeOrbitFeed.instances)
        FakeOrbitFeed.instances.append(self)

        self.connect_calls = 0
        self.receive_calls = 0
        self.resubscribe_calls = 0
        self.closed = False
        self._matches = []
        self.last_frame_kind = "odds"

    async def connect_and_subscribe(self):
        self.connect_calls += 1

        if self.instance_index < self.script.get("fail_first_instances", 0):
            raise RuntimeError("simulated Orbit connect failure")

        return self.script.get("market_count", 3)

    async def resubscribe_all(self):
        self.resubscribe_calls += 1
        return self.script.get("market_count", 3)

    async def receive_next(self):
        self.receive_calls += 1

        fail_after = self.script.get("fail_receive_after")
        if fail_after is not None and self.receive_calls > fail_after:
            raise ConnectionError("simulated Orbit stream drop")

        transient_calls = self.script.get("fail_transient_receive_calls", 0)
        if self.receive_calls <= transient_calls:
            raise KeyError(self.script.get("fail_message", "homeTeam"))

        delay = self.script.get("call_delay", 0.0)
        if delay:
            await asyncio.sleep(delay)

        kinds = self.script.get("frame_kinds")
        if kinds:
            idx = min(self.receive_calls - 1, len(kinds) - 1)
            kind = kinds[idx]
        else:
            kind = self.script.get("frame_kind", "odds")
        self.last_frame_kind = kind
        if kind != "odds":
            return []

        self._matches = [make_match(side="BACK"), make_match(side="LAY")]
        return self._matches

    def get_match_odds(self):
        return self._matches

    async def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def reset_fake_feed_registry():
    FakeOrbitFeed.instances = []
    yield
    FakeOrbitFeed.instances = []


def make_worker(monkeypatch, **script):
    factory = lambda: FakeOrbitFeed(script)  # noqa: E731
    monkeypatch.setattr(worker_module, "OrbitFeed", factory)
    return OrbitWorker()


async def wait_until(predicate, timeout=3.0, interval=0.02):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


# ----------------------------------------------------------------------
# Basic lifecycle / publication
# ----------------------------------------------------------------------

@pytest.mark.anyio
async def test_worker_publishes_matches_after_first_frame(monkeypatch):
    worker = make_worker(monkeypatch)
    worker.start()

    try:
        assert await wait_until(lambda: len(worker.get_matches()) > 0)

        status = worker.get_status()
        assert status["status"] == "running"
        assert status["error"] is None
        assert status["last_update_at"] is not None
        assert status["success_count"] >= 1
        assert status["back_count"] == 1
        assert status["lay_count"] == 1
    finally:
        await worker.stop()


@pytest.mark.anyio
async def test_worker_reuses_single_persistent_feed_across_frames(monkeypatch):
    worker = make_worker(monkeypatch)
    worker.start()

    try:
        assert await wait_until(
            lambda: worker.get_status()["success_count"] >= 5, timeout=3.0
        )
    finally:
        await worker.stop()

    assert len(FakeOrbitFeed.instances) == 1
    assert FakeOrbitFeed.instances[0].connect_calls == 1


@pytest.mark.anyio
async def test_worker_freshness_timestamp_advances_between_frames(monkeypatch):
    worker = make_worker(monkeypatch)
    worker.start()

    try:
        assert await wait_until(lambda: worker.get_status()["success_count"] >= 1)
        first_update = worker.get_status()["last_update_at"]

        assert await wait_until(
            lambda: worker.get_status()["last_update_at"] != first_update,
            timeout=3.0,
        )
        second_update = worker.get_status()["last_update_at"]

        assert second_update > first_update
    finally:
        await worker.stop()


# ----------------------------------------------------------------------
# Reconnection
# ----------------------------------------------------------------------

@pytest.mark.anyio
async def test_worker_reconnects_after_connect_failure(monkeypatch):
    worker = OrbitWorker()
    script = {"fail_first_instances": 1}
    monkeypatch.setattr(worker_module, "OrbitFeed", lambda: FakeOrbitFeed(script))
    monkeypatch.setattr(worker_module, "INITIAL_BACKOFF_SECONDS", 0.05)
    monkeypatch.setattr(worker_module, "MAX_BACKOFF_SECONDS", 0.05)

    worker.start()

    try:
        assert await wait_until(
            lambda: worker.get_status()["status"] == "reconnecting", timeout=2.0
        )
        assert await wait_until(
            lambda: worker.get_status()["status"] == "running", timeout=6.0
        )
    finally:
        await worker.stop()

    assert len(FakeOrbitFeed.instances) == 2
    assert worker.get_status()["error"] is None


@pytest.mark.anyio
async def test_transient_receive_failure_retries_in_place_without_reconnecting(monkeypatch):
    """
    A single malformed-frame-style failure (e.g. the real KeyError:
    'homeTeam' bug from an incomplete catalogue entry -- see
    parsers/orbit/feed.py's per-market try/except) must be retried on
    the SAME feed/session -- no reconnect, no closed websocket, no
    fresh REST catalogue fetch -- exactly the LEVEL 1 escalation from
    the resilience spec.
    """
    monkeypatch.setattr(worker_module, "INPLACE_RETRY_PAUSE_SECONDS", 0.01)

    worker = OrbitWorker()
    script = {"fail_transient_receive_calls": 1}
    monkeypatch.setattr(worker_module, "OrbitFeed", lambda: FakeOrbitFeed(script))

    worker.start()

    try:
        assert await wait_until(lambda: worker.get_status()["success_count"] >= 1, timeout=3.0)

        # Checked BEFORE stop() (which always closes the feed as part
        # of a clean shutdown) -- what matters here is that the feed
        # was never closed WHILE recovering from the transient error.
        assert len(FakeOrbitFeed.instances) == 1
        assert FakeOrbitFeed.instances[0].connect_calls == 1
        assert FakeOrbitFeed.instances[0].closed is False
        status = worker.get_status()
        assert status["reconnect_count"] == 0
        assert status["failed_count"] >= 1
    finally:
        await worker.stop()


@pytest.mark.anyio
async def test_persistent_transient_receive_failures_eventually_force_reconnect(monkeypatch):
    """Bounded safety net: an unrecognized error that keeps recurring
    on receive_next() must still eventually force a real reconnect."""
    monkeypatch.setattr(worker_module, "INPLACE_RETRY_PAUSE_SECONDS", 0.01)
    monkeypatch.setattr(worker_module, "INITIAL_BACKOFF_SECONDS", 0.02)
    monkeypatch.setattr(worker_module, "MAX_BACKOFF_SECONDS", 0.02)

    worker = OrbitWorker()
    # Fails every receive_next() call on instance 0 forever (large
    # transient-failure count), so the bounded MAX_INPLACE_RETRIES
    # safety net -- not an eventual success -- is what forces reconnect.
    script = {"fail_transient_receive_calls": 1_000_000}
    monkeypatch.setattr(worker_module, "OrbitFeed", lambda: FakeOrbitFeed(script))

    worker.start()

    try:
        assert await wait_until(
            lambda: len(FakeOrbitFeed.instances) >= 2, timeout=5.0
        )
    finally:
        await worker.stop()

    assert FakeOrbitFeed.instances[0].closed is True
    assert worker.get_status()["reconnect_count"] >= 1


@pytest.mark.anyio
async def test_worker_reconnects_after_mid_session_drop(monkeypatch):
    worker = OrbitWorker()
    script = {"fail_receive_after": 2}
    monkeypatch.setattr(worker_module, "OrbitFeed", lambda: FakeOrbitFeed(script))
    monkeypatch.setattr(worker_module, "INITIAL_BACKOFF_SECONDS", 0.05)
    monkeypatch.setattr(worker_module, "MAX_BACKOFF_SECONDS", 0.05)

    worker.start()

    try:
        assert await wait_until(
            lambda: len(FakeOrbitFeed.instances) >= 2, timeout=3.0
        )
        assert await wait_until(
            lambda: worker.get_status()["status"] == "running", timeout=3.0
        )
    finally:
        await worker.stop()

    assert FakeOrbitFeed.instances[0].closed is True


# ----------------------------------------------------------------------
# Shutdown / idempotency
# ----------------------------------------------------------------------

@pytest.mark.anyio
async def test_worker_stop_closes_feed_and_cancels_task(monkeypatch):
    worker = make_worker(monkeypatch)
    worker.start()

    assert await wait_until(lambda: len(FakeOrbitFeed.instances) == 1)
    assert await wait_until(lambda: worker.get_status()["success_count"] >= 1)

    await worker.stop(timeout=5)

    assert worker.get_status()["status"] == "stopped"
    assert FakeOrbitFeed.instances[0].closed is True
    assert worker._task.done()


@pytest.mark.anyio
async def test_worker_start_is_idempotent(monkeypatch):
    worker = make_worker(monkeypatch)
    worker.start()
    first_task = worker._task

    worker.start()
    second_task = worker._task

    assert first_task is second_task

    await worker.stop()


@pytest.mark.anyio
async def test_heartbeats_do_not_count_as_odds_or_reconnect(monkeypatch):
    """SockJS heartbeats prove the socket is alive; they must not
    bump last_update_at (odds freshness) or tear down the session."""
    worker = make_worker(monkeypatch, frame_kind="heartbeat")
    worker.start()

    try:
        assert await wait_until(
            lambda: worker.get_status()["last_heartbeat_at"] is not None,
            timeout=3.0,
        )
        await asyncio.sleep(0.2)
        status = worker.get_status()
        assert status["last_update_at"] is None
        assert status["success_count"] == 0
        assert status["reconnect_count"] == 0
        assert len(FakeOrbitFeed.instances) == 1
        assert FakeOrbitFeed.instances[0].connect_calls == 1
        assert FakeOrbitFeed.instances[0].closed is False
    finally:
        await worker.stop()


@pytest.mark.anyio
async def test_odds_frame_after_heartbeats_uses_same_session(monkeypatch):
    worker = make_worker(
        monkeypatch,
        frame_kinds=["heartbeat", "heartbeat", "odds"],
    )
    worker.start()

    try:
        assert await wait_until(
            lambda: worker.get_status()["success_count"] >= 1, timeout=3.0
        )
        status = worker.get_status()
        assert status["reconnect_count"] == 0
        assert len(FakeOrbitFeed.instances) == 1
        for match in worker.get_matches():
            assert match.side in ("BACK", "LAY")
            assert match.side is not None
    finally:
        await worker.stop()


@pytest.mark.anyio
async def test_stale_odds_with_heartbeats_resubscribes_without_reconnect(monkeypatch):
    monkeypatch.setattr(worker_module, "ODDS_STALE_WARN_SECONDS", 0.05)
    monkeypatch.setattr(worker_module, "ODDS_UNHEALTHY_SECONDS", 0.05)
    monkeypatch.setattr(worker_module, "RESUBSCRIBE_COOLDOWN_SECONDS", 0.05)
    monkeypatch.setattr(worker_module, "HEALTH_LOG_SECONDS", 10.0)

    worker = make_worker(
        monkeypatch,
        call_delay=0.02,
        frame_kinds=["odds"] + ["heartbeat"] * 80,
    )
    worker.start()

    try:
        assert await wait_until(
            lambda: worker.get_status()["success_count"] >= 1, timeout=3.0
        )
        assert await wait_until(
            lambda: FakeOrbitFeed.instances[0].resubscribe_calls >= 1,
            timeout=3.0,
        )
        assert FakeOrbitFeed.instances[0].connect_calls == 1
        assert worker.get_status()["reconnect_count"] == 0
        assert FakeOrbitFeed.instances[0].closed is False
    finally:
        await worker.stop()
