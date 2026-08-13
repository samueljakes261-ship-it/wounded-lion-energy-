"""
Regression test using a REAL captured Orbit websocket frame
(tests/sample_market.json, market "Atletico FC Cali v Independiente
Yumbo") to prove OrbitParser + OrbitAdapter extract the correct
top-of-book BACK/LAY prices end-to-end.

This is the exact raw shape the bug was found in: each runner's
"bdatb"/"bdatl" carries 3 explicitly-indexed price levels, and "catb"/
"catl" are sorted by ascending numeric price (NOT best-price-first for
BACK). Before the fix, the adapter read catb[0][0] and returned the
WORST back price instead of the best.

tests/sample_market.json's raw "rc" entries don't include a
"marketDefinition" or catalogue (it's a lightweight price-only frame,
which the real pipeline in parsers/orbit/feed.py already skips
entirely for that reason -- see receive_next()). To exercise
OrbitParser.parse() itself, this test pairs that real "rc" price data
with a synthetic marketDefinition/catalogue, matching the real
match ("Atletico FC Cali v Independiente Yumbo").
"""

import json

from parsers.orbit.adapter import OrbitAdapter
from parsers.orbit.parser import OrbitParser


def _load_real_rc():
    with open("tests/sample_market.json", encoding="utf-8") as f:
        raw = json.load(f)
    return raw["rc"]


def _build_frame_and_catalogue():
    rc = _load_real_rc()

    # Real selection ids from the fixture, real match name. Orbit's
    # actual catalogue runner order is [home, away, draw] (see
    # parsers/orbit/adapter.py) -- deliberately used here, not
    # [home, draw, away], so this test also guards the runner-order
    # bug using real ids.
    home_id, away_id, draw_id = 94441547, 18225671, 58805

    message = {
        "id": "1.260439595",
        "marketDefinition": {
            "eventId": "35867737",
            "status": "OPEN",
            "inPlay": True,
        },
        "rc": rc,
    }

    catalogue = {
        "runners": [
            {"selectionId": home_id, "runnerName": "Atletico FC Cali"},
            {"selectionId": away_id, "runnerName": "Independiente Yumbo"},
            {"selectionId": draw_id, "runnerName": "The Draw"},
        ],
        "event": {
            "homeTeam": "Atletico FC Cali",
            "awayTeam": "Independiente Yumbo",
        },
        "competition": {"name": "Colombia Primera A"},
        "eventType": {"name": "Soccer"},
        "marketName": "Match Odds",
        "marketStartTime": 1_785_198_600_000,
        "totalMatched": 689.42,
    }

    return message, catalogue


def test_real_frame_back_prices_use_index_zero_not_catb_first_element():
    message, catalogue = _build_frame_and_catalogue()

    market = OrbitParser.parse(message, catalogue)
    match = OrbitAdapter.to_match_odds(market, side="BACK")

    assert match is not None
    assert match.side == "BACK"

    # Ground truth from tests/sample_market.json's "bdatb" index 0:
    # home(94441547)=2.26, away(18225671)=3.85, draw(58805)=3.1.
    # The old "catb"/"catl"-based code would have returned the
    # ascending-sort MINIMUM instead: 2.22 / 3.75 / 3.0.
    assert match.home_odds == 2.26
    assert match.away_odds == 3.85
    assert match.draw_odds == 3.1


def test_real_frame_lay_prices_are_correct():
    message, catalogue = _build_frame_and_catalogue()

    market = OrbitParser.parse(message, catalogue)
    match = OrbitAdapter.to_match_odds(market, side="LAY")

    assert match is not None
    assert match.side == "LAY"

    # Ground truth from "bdatl" index 0: home=2.38, away=4.2, draw=3.25.
    assert match.home_odds == 2.38
    assert match.away_odds == 4.2
    assert match.draw_odds == 3.25
