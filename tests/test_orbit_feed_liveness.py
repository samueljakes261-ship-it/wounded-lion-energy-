"""
Orbit websocket liveness: SockJS heartbeats must keep the session
alive without being treated as odds updates, and catalogue-refresh
failures must not tear down the price socket.
"""
import asyncio

import pytest

from parsers.orbit.client import ORBIT_HEARTBEAT, is_orbit_heartbeat
from parsers.orbit.feed import OrbitFeed


class _QueueClient:
    def __init__(self, frames):
        self._frames = list(frames)
        self.closed = False
        self.subscribe_calls = []

    async def receive(self):
        if not self._frames:
            await asyncio.sleep(0)
            return None
        return self._frames.pop(0)

    async def subscribe(self, market_id, event_id):
        self.subscribe_calls.append((market_id, event_id))

    async def close(self):
        self.closed = True


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _make_feed(frames):
    feed = OrbitFeed()
    feed.client = _QueueClient(frames)
    feed._catalogue["1.1"] = {
        "marketId": "1.1",
        "runners": [
            {"selectionId": 1, "runnerName": "Home FC"},
            {"selectionId": 2, "runnerName": "Away FC"},
            {"selectionId": 3, "runnerName": "The Draw"},
        ],
        "event": {"homeTeam": "Home FC", "awayTeam": "Away FC"},
        "competition": {"name": "Test League"},
        "eventType": {"name": "Soccer"},
        "marketName": "Match Odds",
        "marketStartTime": 1_700_000_000_000,
        "totalMatched": 500.0,
    }
    feed._last_catalogue_refresh = float("inf")
    return feed


@pytest.mark.anyio
async def test_heartbeat_frame_is_liveness_not_odds():
    feed = _make_feed([ORBIT_HEARTBEAT])
    matches = await feed.receive_next()
    assert matches == []
    assert feed.last_frame_kind == "heartbeat"
    assert is_orbit_heartbeat(ORBIT_HEARTBEAT)


@pytest.mark.anyio
async def test_true_socket_close_raises_connection_error():
    feed = _make_feed([])
    with pytest.raises(ConnectionError):
        await feed.receive_next()


@pytest.mark.anyio
async def test_catalogue_refresh_failure_does_not_close_socket(monkeypatch):
    feed = _make_feed([ORBIT_HEARTBEAT])
    feed._closed = False

    def boom():
        raise RuntimeError("catalogue rest failed")

    monkeypatch.setattr("parsers.orbit.feed.get_all_live_markets", boom)

    with pytest.raises(RuntimeError):
        await feed._refresh_catalogue()

    assert feed.client.closed is False
    matches = await feed.receive_next()
    assert feed.last_frame_kind == "heartbeat"
    assert matches == []
