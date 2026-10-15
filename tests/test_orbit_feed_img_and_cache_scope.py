"""OrbitFeed img:true reset + per-market runner cache."""

import asyncio

import pytest

from parsers.orbit.feed import OrbitFeed


HOME, AWAY, DRAW = 100, 200, 58805


def _ladder(odds):
    return [{"index": 0, "odds": odds, "amount": 10.0}]


def _catalogue(market_id, home, away):
    return {
        "marketId": market_id,
        "runners": [
            {"selectionId": HOME, "runnerName": home},
            {"selectionId": AWAY, "runnerName": away},
            {"selectionId": DRAW, "runnerName": "The Draw"},
        ],
        "event": {"homeTeam": home, "awayTeam": away, "id": "e1"},
        "competition": {"name": "Test League"},
        "eventType": {"name": "Soccer"},
        "marketName": "Match Odds",
        "marketStartTime": 1_700_000_000_000,
        "totalMatched": 500.0,
    }


def _image(market_id, home_back, draw_back, away_back):
    return {
        "id": market_id,
        "img": True,
        "marketDefinition": {"eventId": "e1", "status": "OPEN", "inPlay": True},
        "rc": [
            {"id": HOME, "bdatb": _ladder(home_back), "bdatl": _ladder(home_back + 0.1), "tv": 1},
            {"id": AWAY, "bdatb": _ladder(away_back), "bdatl": _ladder(away_back + 0.1), "tv": 1},
            {"id": DRAW, "bdatb": _ladder(draw_back), "bdatl": _ladder(draw_back + 0.1), "tv": 1},
        ],
    }


def _delta(market_id, selection_id, new_back):
    return {
        "id": market_id,
        "img": False,
        "marketDefinition": {"eventId": "e1", "status": "OPEN", "inPlay": True},
        "rc": [{"id": selection_id, "bdatb": _ladder(new_back), "tv": 2}],
    }


class _QueueClient:
    def __init__(self, frames):
        self._frames = list(frames)
        self.ws = object()

    async def receive(self):
        if not self._frames:
            await asyncio.sleep(0)
            return None
        return self._frames.pop(0)

    async def close(self):
        return None


def _feed(frames, catalogues):
    feed = OrbitFeed()
    feed.client = _QueueClient(frames)
    for entry in catalogues:
        feed._catalogue[entry["marketId"]] = entry
    feed._last_catalogue_refresh = float("inf")
    return feed


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_img_true_removes_runner_omitted_from_full_image():
    feed = _feed(
        [
            _image("1.1", 2.0, 3.4, 3.8),
            {
                "id": "1.1",
                "img": True,
                "marketDefinition": {"eventId": "e1", "status": "OPEN", "inPlay": True},
                "rc": [
                    {"id": HOME, "bdatb": _ladder(2.0), "bdatl": _ladder(2.1), "tv": 1},
                    {"id": AWAY, "bdatb": _ladder(3.8), "bdatl": _ladder(3.9), "tv": 1},
                ],
            },
        ],
        [_catalogue("1.1", "Home FC", "Away FC")],
    )

    first = await feed.receive_next()
    assert first
    second = await feed.receive_next()
    assert second == []
    assert DRAW not in feed._runner_ladders["1.1"]
    assert feed.get_match_odds() == []


@pytest.mark.anyio
async def test_empty_delta_keeps_existing_market_odds():
    feed = _feed(
        [
            _image("1.1", 2.0, 3.4, 3.8),
            {"id": "1.1", "img": False, "rc": []},
        ],
        [_catalogue("1.1", "Home FC", "Away FC")],
    )
    first = await feed.receive_next()
    after = await feed.receive_next()
    assert first
    assert after
    match = next(m for m in after if m.side == "BACK")
    assert (match.home_odds, match.draw_odds, match.away_odds) == (2.0, 3.4, 3.8)
    cached = feed._runner_ladders["1.1"]
    assert HOME in cached and DRAW in cached and AWAY in cached


@pytest.mark.anyio
async def test_shared_draw_id_does_not_leak_across_markets():
    feed = _feed(
        [
            _image("1.A", 2.0, 3.10, 4.0),
            _image("1.B", 1.5, 4.50, 5.0),
            _delta("1.A", HOME, 2.20),
        ],
        [
            _catalogue("1.A", "Alpha FC", "Beta FC"),
            _catalogue("1.B", "Gamma FC", "Delta FC"),
        ],
    )
    await feed.receive_next()
    await feed.receive_next()
    updated_a = await feed.receive_next()

    assert updated_a
    match_a = next(m for m in updated_a if m.side == "BACK")
    assert match_a.home_odds == 2.20
    assert match_a.draw_odds == 3.10
    assert feed._runner_ladders["1.B"][DRAW]["back"][0]["odds"] == 4.50


def _zero_ladder():
    return [{"index": 0, "odds": 0.0, "amount": 0.0}]


@pytest.mark.anyio
async def test_unquoted_shared_draw_does_not_blank_other_soccer_markets():
    """
    Production DEGRADED path: Draw selection 58805 is reused on every
    soccer Match Odds market. A global runner cache lets one market's
    unquoted DRAW (odds=0 placeholder) overwrite every other market's
    draw ladder. OrbitAdapter then rejects those 1X2 books, receive_next
    returns no MatchOdds, last_update_at goes stale, collector=DEGRADED.

    Per-market cache must keep market A's quoted draw after market B
    publishes an unquoted DRAW on the same selection id.
    """
    unquoted_b = {
        "id": "1.B",
        "img": True,
        "marketDefinition": {"eventId": "e1", "status": "OPEN", "inPlay": True},
        "rc": [
            {"id": HOME, "bdatb": _ladder(1.5), "bdatl": _ladder(1.6), "tv": 1},
            {"id": AWAY, "bdatb": _ladder(5.0), "bdatl": _ladder(5.1), "tv": 1},
            {"id": DRAW, "bdatb": _zero_ladder(), "bdatl": _zero_ladder(), "tv": 1},
        ],
    }
    feed = _feed(
        [
            _image("1.A", 2.0, 3.10, 4.0),
            unquoted_b,
            _delta("1.A", HOME, 2.20),
        ],
        [
            _catalogue("1.A", "Alpha FC", "Beta FC"),
            _catalogue("1.B", "Gamma FC", "Delta FC"),
        ],
    )
    await feed.receive_next()
    await feed.receive_next()
    updated_a = await feed.receive_next()

    assert updated_a, "market A delta must still produce MatchOdds"
    match_a = next(m for m in updated_a if m.side == "BACK")
    assert match_a.home_odds == 2.20
    assert match_a.draw_odds == 3.10
    assert match_a.away_odds == 4.0
