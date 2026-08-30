"""
Regression test for the real, repeatedly-observed production bug:

    KeyError: 'homeTeam'

raised from inside OrbitParser.parse() when a single market's
catalogue entry is malformed/incomplete (e.g. an outright/futures
market with no ordinary two-team "event.homeTeam"/"awayTeam" pair, or
a REST/WebSocket race leaving a partial catalogue entry).

Before this fix, that exception propagated all the way up through
OrbitFeed.receive_next() to OrbitWorker._run(), which treated ANY
exception as "the whole session is dead" and tore down + fully
reconnected (fresh REST catalogue fetch + resubscribe to EVERY live
market) for a single bad market's single frame -- a
PARSER_FAILURE being treated as, and paying the cost of, a
ZENROWS_FAILURE/CONNECTION_FAILURE.

The fix: OrbitFeed.receive_next() now isolates a single market's own
parse/adapt failure, logs it, and returns an empty result for THAT
frame only -- the persistent websocket session itself is left
completely untouched.
"""

import asyncio

import pytest

from parsers.orbit.feed import OrbitFeed


GOOD_MARKET_ID = "1.100"
BAD_MARKET_ID = "1.999"

GOOD_CATALOGUE_ENTRY = {
    "marketId": GOOD_MARKET_ID,
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

# Malformed on purpose: no "event" key at all, mirroring the real
# production entries that triggered "KeyError: 'homeTeam'".
BAD_CATALOGUE_ENTRY = {
    "marketId": BAD_MARKET_ID,
    "runners": [
        {"selectionId": 4, "runnerName": "Runner A"},
        {"selectionId": 5, "runnerName": "Runner B"},
    ],
    "competition": {"name": "Test League"},
    "eventType": {"name": "Soccer"},
    "marketName": "Outright Winner",
    "marketStartTime": 1_700_000_000_000,
    "totalMatched": 100.0,
}


def _ladder(odds, amount=10.0):
    return [{"index": 0, "odds": odds, "amount": amount}]


def _frame(market_id, selection_ids_and_prices):
    return {
        "id": market_id,
        "marketDefinition": {"eventId": "1", "status": "OPEN", "inPlay": True},
        "img": True,
        "rc": [
            {"id": sid, "bdatb": _ladder(price), "bdatl": [], "tv": 10}
            for sid, price in selection_ids_and_prices
        ],
    }


class _QueueClient:
    """Minimal stand-in for OrbitWebSocketClient: yields pre-scripted
    frames from a queue instead of a real websocket."""

    def __init__(self, frames):
        self._frames = list(frames)
        self.closed = False

    async def receive(self):
        if not self._frames:
            await asyncio.sleep(0)
            return None
        return self._frames.pop(0)

    async def close(self):
        self.closed = True


def _make_feed(catalogue_entries, frames):
    feed = OrbitFeed()
    feed.client = _QueueClient(frames)
    for entry in catalogue_entries:
        feed._catalogue[entry["marketId"]] = entry
    # Prevent _maybe_refresh_catalogue() from making a real REST call.
    feed._last_catalogue_refresh = float("inf")
    return feed


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_malformed_market_catalogue_entry_does_not_raise():
    """The historical KeyError('homeTeam') must be caught and
    swallowed at the single-frame level, never propagate out of
    receive_next()."""

    feed = _make_feed(
        [BAD_CATALOGUE_ENTRY],
        [_frame(BAD_MARKET_ID, [(4, 2.0), (5, 3.0)])],
    )

    matches = await feed.receive_next()

    assert matches == []


@pytest.mark.anyio
async def test_malformed_market_does_not_poison_other_markets(monkeypatch):
    """A bad frame for market A must not prevent a subsequent GOOD
    frame for market B from being parsed normally on the SAME
    session/feed -- proving the isolation is per-frame, not a
    session-wide failure flag."""

    feed = _make_feed(
        [BAD_CATALOGUE_ENTRY, GOOD_CATALOGUE_ENTRY],
        [
            _frame(BAD_MARKET_ID, [(4, 2.0), (5, 3.0)]),
            _frame(GOOD_MARKET_ID, [(1, 2.10), (2, 3.60), (3, 3.40)]),
        ],
    )

    first = await feed.receive_next()
    assert first == []

    second = await feed.receive_next()
    assert len(second) >= 1
    assert any(m.home_team == "Home FC" for m in second)


@pytest.mark.anyio
async def test_malformed_market_never_closes_the_session():
    feed = _make_feed(
        [BAD_CATALOGUE_ENTRY],
        [_frame(BAD_MARKET_ID, [(4, 2.0), (5, 3.0)])],
    )

    await feed.receive_next()

    assert feed.client.closed is False
