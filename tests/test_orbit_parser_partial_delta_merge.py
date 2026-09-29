"""
Regression test for the "Orbit odds go stale after the first frame"
bug (Issue 1 -- displayed odds not matching the live bookmaker).

Orbit's websocket protocol mirrors Betfair's exchange streaming API:
a frame carries "img": true for a full snapshot (every runner
present in "rc"), but is otherwise a PARTIAL delta that only includes
the runner(s) whose own price just changed (see
tests/sample_market.json, a REAL captured full-image frame, for the
"img" field).

Before this fix, OrbitParser.parse() built an empty back/lay ladder
for any runner absent from a given frame's "rc". OrbitAdapter then
rejected the whole market as "not fully quoted" whenever even ONE of
the three runners was missing -- which is the common case for a
partial delta -- so OrbitFeed's per-market cache (_matches_by_market)
was never updated by that frame at all. In production this froze
every market at its very first full-image snapshot the instant only
one runner ticked (which happens on almost every subsequent frame),
while the real exchange price kept moving.

The fix: OrbitParser.parse() accepts an optional runner_cache dict
(owned by OrbitFeed, one per session) so a runner absent from "rc" in
THIS frame resolves to its last known ladder instead of "unquoted".
"""

from parsers.orbit.adapter import OrbitAdapter
from parsers.orbit.parser import OrbitParser


HOME_ID, AWAY_ID, DRAW_ID = 100, 200, 300

CATALOGUE = {
    "runners": [
        {"selectionId": HOME_ID, "runnerName": "Home FC"},
        {"selectionId": AWAY_ID, "runnerName": "Away FC"},
        {"selectionId": DRAW_ID, "runnerName": "The Draw"},
    ],
    "event": {"homeTeam": "Home FC", "awayTeam": "Away FC"},
    "competition": {"name": "Test League"},
    "eventType": {"name": "Soccer"},
    "marketName": "Match Odds",
    "marketStartTime": 1_700_000_000_000,
    "totalMatched": 500.0,
}


def _ladder(odds, amount=10.0):
    return [{"index": 0, "odds": odds, "amount": amount}]


def _full_image_frame(home_back, draw_back, away_back):
    return {
        "id": "1.1",
        "marketDefinition": {"eventId": "1", "status": "OPEN", "inPlay": True},
        "img": True,
        "rc": [
            {"id": HOME_ID, "bdatb": _ladder(home_back), "bdatl": [], "tv": 10},
            {"id": AWAY_ID, "bdatb": _ladder(away_back), "bdatl": [], "tv": 10},
            {"id": DRAW_ID, "bdatb": _ladder(draw_back), "bdatl": [], "tv": 10},
        ],
    }


def _partial_delta_frame(selection_id, new_back):
    """A realistic delta: only ONE runner (the one that just changed
    price) is present in "rc"."""
    return {
        "id": "1.1",
        "marketDefinition": {"eventId": "1", "status": "OPEN", "inPlay": True},
        "img": False,
        "rc": [
            {"id": selection_id, "bdatb": _ladder(new_back), "bdatl": [], "tv": 20},
        ],
    }


def test_without_runner_cache_a_partial_delta_drops_the_whole_market():
    """
    Documents the OLD (buggy, still-reachable-if-misused) behavior:
    calling parse() with no runner_cache on a partial delta produces a
    market with 2 unquoted runners, so the adapter correctly refuses
    to synthesize a price for them -- proving the bug is real, not a
    fixture artifact.
    """

    frame = _partial_delta_frame(HOME_ID, 3.50)

    market = OrbitParser.parse(frame, CATALOGUE)  # no runner_cache
    match = OrbitAdapter.to_match_odds(market, side="BACK")

    assert match is None


def test_runner_cache_resolves_partial_delta_to_last_known_price():
    """
    The actual fix: a shared runner_cache lets a partial delta for ONE
    runner still produce a fully-quoted market, with the OTHER two
    runners resolved to their last known (real, not fabricated) price.
    """

    cache: dict = {}

    # 1. Full image establishes the baseline for all three runners.
    full = _full_image_frame(home_back=2.00, draw_back=3.40, away_back=3.80)
    market = OrbitParser.parse(full, CATALOGUE, runner_cache=cache)
    match = OrbitAdapter.to_match_odds(market, side="BACK")

    assert match is not None
    assert (match.home_odds, match.draw_odds, match.away_odds) == (2.00, 3.40, 3.80)

    # 2. A partial delta: ONLY the home runner's price actually moved.
    delta = _partial_delta_frame(HOME_ID, new_back=1.85)
    market = OrbitParser.parse(delta, CATALOGUE, runner_cache=cache)
    match = OrbitAdapter.to_match_odds(market, side="BACK")

    assert match is not None, (
        "A partial delta must still produce a fully-quoted market when "
        "a runner_cache is supplied -- this is the actual bug fix."
    )

    # Home reflects the NEW price from this frame...
    assert match.home_odds == 1.85
    # ...while draw/away correctly retain their last known (unchanged)
    # prices, rather than being dropped or reset to zero.
    assert match.draw_odds == 3.40
    assert match.away_odds == 3.80


def test_runner_cache_keeps_updating_across_many_sequential_deltas():
    """
    Simulates a realistic sequence of single-runner deltas (as Orbit
    actually sends them) and proves every runner's price stays live
    and independently up to date, instead of freezing after frame 1.
    """

    cache: dict = {}

    full = _full_image_frame(home_back=2.00, draw_back=3.40, away_back=3.80)
    OrbitParser.parse(full, CATALOGUE, runner_cache=cache)

    sequence = [
        (HOME_ID, 1.90),
        (DRAW_ID, 3.55),
        (AWAY_ID, 4.10),
        (HOME_ID, 1.95),
    ]

    last_match = None
    for selection_id, new_price in sequence:
        frame = _partial_delta_frame(selection_id, new_price)
        market = OrbitParser.parse(frame, CATALOGUE, runner_cache=cache)
        last_match = OrbitAdapter.to_match_odds(market, side="BACK")
        assert last_match is not None

    # Final state reflects the LAST value seen for each runner, not
    # the original full-image snapshot.
    assert last_match.home_odds == 1.95
    assert last_match.draw_odds == 3.55
    assert last_match.away_odds == 4.10


def test_runner_absent_before_ever_appearing_in_any_frame_stays_unquoted():
    """A runner that has never appeared in ANY frame (not even the
    initial image) has no cached price to fall back to, and must
    still be treated as unquoted -- the cache never fabricates a price
    out of nothing."""

    cache: dict = {}

    # Only home and away appear -- draw has never been seen at all.
    frame = {
        "id": "1.1",
        "marketDefinition": {"eventId": "1", "status": "OPEN", "inPlay": True},
        "img": True,
        "rc": [
            {"id": HOME_ID, "bdatb": _ladder(2.0), "bdatl": [], "tv": 10},
            {"id": AWAY_ID, "bdatb": _ladder(3.5), "bdatl": [], "tv": 10},
        ],
    }

    market = OrbitParser.parse(frame, CATALOGUE, runner_cache=cache)
    match = OrbitAdapter.to_match_odds(market, side="BACK")

    assert match is None


def test_partial_bdatl_only_frame_preserves_bdatb_from_cache():
    """
    A single runner's entry in "rc" can itself only carry ONE of
    bdatb/bdatl (e.g. only the lay side moved) -- the other side must
    resolve from cache too, not just the ladder for absent runners.
    """

    cache: dict = {}

    full = {
        "id": "1.1",
        "marketDefinition": {"eventId": "1", "status": "OPEN", "inPlay": True},
        "img": True,
        "rc": [
            {
                "id": HOME_ID,
                "bdatb": _ladder(2.00),
                "bdatl": _ladder(2.10),
                "tv": 10,
            },
            {"id": AWAY_ID, "bdatb": _ladder(3.5), "bdatl": _ladder(3.6), "tv": 10},
            {"id": DRAW_ID, "bdatb": _ladder(3.4), "bdatl": _ladder(3.5), "tv": 10},
        ],
    }
    OrbitParser.parse(full, CATALOGUE, runner_cache=cache)

    # This delta only carries the home runner's LAY ladder.
    lay_only_delta = {
        "id": "1.1",
        "marketDefinition": {"eventId": "1", "status": "OPEN", "inPlay": True},
        "img": False,
        "rc": [{"id": HOME_ID, "bdatl": _ladder(2.05), "tv": 15}],
    }

    market = OrbitParser.parse(lay_only_delta, CATALOGUE, runner_cache=cache)
    back = OrbitAdapter.to_match_odds(market, side="BACK")
    lay = OrbitAdapter.to_match_odds(market, side="LAY")

    assert back is not None
    assert back.home_odds == 2.00  # unchanged BACK side, from cache

    assert lay is not None
    assert lay.home_odds == 2.05  # new LAY side, from this frame


def test_partial_delta_without_market_definition_still_parses():
    """Live deltas sometimes omit marketDefinition; odds must still update."""
    cache: dict = {}
    full = _full_image_frame(home_back=2.00, draw_back=3.40, away_back=3.80)
    OrbitParser.parse(full, CATALOGUE, runner_cache=cache)

    delta = _partial_delta_frame(HOME_ID, 1.85)
    del delta["marketDefinition"]

    market = OrbitParser.parse(delta, CATALOGUE, runner_cache=cache)
    match = OrbitAdapter.to_match_odds(market, side="BACK")

    assert match is not None
    assert match.side == "BACK"
    assert match.home_odds == 1.85
    assert match.draw_odds == 3.40
    assert match.away_odds == 3.80
