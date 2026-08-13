"""
Deterministic tests for OrbitAdapter's BACK/LAY handling
(parsers/orbit/adapter.py). No network -- built directly from
parsers.orbit.models fixtures.

Regression coverage for two real bugs found by comparing the parser's
output against actual Orbit raw frames (see parsers/orbit/diagnose_raw.py
and the investigation notes in adapter.py/parser.py):

1. Price-ladder bug: "bdatb"/"bdatl" entries carry an explicit "index"
   (0 = Orbit's own "best price" marker). Picking any other level, or
   assuming array position 0 is always best, silently returns the
   wrong price -- test_top_price_uses_index_zero_not_array_position
   and test_multi_level_ladder_picks_correct_back_and_lay_price cover
   this with intentionally out-of-order/multi-level fixtures.

2. Runner-order bug: Orbit's runner order is NOT [home, draw, away] --
   live data shows it is actually [home, away, draw]. Unpacking
   positionally swapped the draw and away odds. Every fixture below
   deliberately places the runners as [home, away, draw] (matching
   live Orbit data) to prove OrbitAdapter identifies them by NAME, not
   position -- test_runner_order_home_away_draw_is_resolved_by_name
   covers this explicitly.
"""

from parsers.orbit.adapter import OrbitAdapter
from parsers.orbit.models import MarketOdds, RunnerOdds


def ladder(*odds_values):
    """
    Build a "bdatb"/"bdatl"-shaped ladder: a list of
    {"index", "odds", "amount"} dicts, index assigned in the order
    given. Passing odds out of numeric order is intentional in some
    tests -- index, not array/price order, determines "best".
    """
    return [
        {"index": i, "odds": price, "amount": 100}
        for i, price in enumerate(odds_values)
        if price is not None
    ]


def make_market(home_back=None, home_lay=None,
                 draw_back=None, draw_lay=None,
                 away_back=None, away_lay=None,
                 runner_order=("home", "away", "draw")):

    def one_level(price):
        return ladder(price) if price is not None else []

    runners_by_role = {
        "home": RunnerOdds(
            1, name="Home FC",
            back=one_level(home_back), lay=one_level(home_lay),
            traded_volume=0,
        ),
        "away": RunnerOdds(
            2, name="Away FC",
            back=one_level(away_back), lay=one_level(away_lay),
            traded_volume=0,
        ),
        "draw": RunnerOdds(
            3, name="The Draw",
            back=one_level(draw_back), lay=one_level(draw_lay),
            traded_volume=0,
        ),
    }

    return MarketOdds(
        market_id="1.123",
        event_id="999",
        market_status="OPEN",
        in_play=True,
        # Mirrors live Orbit ordering: [home, away, draw], NOT
        # [home, draw, away] -- see module docstring.
        runners=[runners_by_role[role] for role in runner_order],
        home_team="Home FC",
        away_team="Away FC",
        competition="Test League",
        sport="Soccer",
        market_name="Match Odds",
        start_time=1_700_000_000_000,
        total_matched=1000.0,
    )


def test_back_side_produces_match_odds_tagged_back():
    market = make_market(home_back=2.10, draw_back=3.40, away_back=3.60)

    match = OrbitAdapter.to_match_odds(market, side="BACK")

    assert match is not None
    assert match.side == "BACK"
    assert match.bookmaker == "Orbit"
    assert match.home_odds == 2.10
    assert match.draw_odds == 3.40
    assert match.away_odds == 3.60


def test_lay_side_produces_match_odds_tagged_lay():
    market = make_market(home_lay=2.20, draw_lay=3.50, away_lay=3.70)

    match = OrbitAdapter.to_match_odds(market, side="LAY")

    assert match is not None
    assert match.side == "LAY"
    assert match.home_odds == 2.20


def test_missing_price_on_requested_side_returns_none():
    # Only BACK is quoted -- requesting LAY must not fabricate a price.
    market = make_market(home_back=2.10, draw_back=3.40, away_back=3.60)

    assert OrbitAdapter.to_match_odds(market, side="LAY") is None


def test_non_three_runner_market_returns_none():
    market = make_market(home_back=2.10, draw_back=3.40, away_back=3.60)
    market.runners = market.runners[:2]

    assert OrbitAdapter.to_match_odds(market, side="BACK") is None


def test_both_sides_helper_returns_only_fully_quoted_sides():
    # BACK fully quoted, LAY only partially quoted (draw missing).
    market = make_market(
        home_back=2.10, draw_back=3.40, away_back=3.60,
        home_lay=2.20, away_lay=3.70,  # draw_lay intentionally omitted
    )

    matches = OrbitAdapter.to_match_odds_both_sides(market)

    sides = {m.side for m in matches}
    assert sides == {"BACK"}


def test_both_sides_helper_returns_both_when_fully_quoted():
    market = make_market(
        home_back=2.10, draw_back=3.40, away_back=3.60,
        home_lay=2.20, draw_lay=3.50, away_lay=3.70,
    )

    matches = OrbitAdapter.to_match_odds_both_sides(market)

    sides = {m.side for m in matches}
    assert sides == {"BACK", "LAY"}

    back = next(m for m in matches if m.side == "BACK")
    lay = next(m for m in matches if m.side == "LAY")

    # BACK price must always be the back ladder, never accidentally
    # the lay ladder or vice versa.
    assert back.home_odds == 2.10
    assert lay.home_odds == 2.20


def test_runner_order_home_away_draw_is_resolved_by_name():
    """
    Regression test for the draw/away swap bug: even though the
    runners list is ordered [home, away, draw] (the real Orbit order),
    each outcome's price must land on the correct field.
    """
    market = make_market(
        home_back=2.10, away_back=25.0, draw_back=3.40,
        runner_order=("home", "away", "draw"),
    )

    match = OrbitAdapter.to_match_odds(market, side="BACK")

    assert match is not None
    assert match.home_odds == 2.10
    assert match.draw_odds == 3.40
    assert match.away_odds == 25.0


def test_runner_order_is_irrelevant_when_shuffled_further():
    """
    Same as above but with a third, differently-shuffled order, to
    prove the mapping is genuinely name-based and not just "happens to
    also work for a second hard-coded order".
    """
    market = make_market(
        home_back=2.10, away_back=25.0, draw_back=3.40,
        runner_order=("draw", "home", "away"),
    )

    match = OrbitAdapter.to_match_odds(market, side="BACK")

    assert match is not None
    assert match.home_odds == 2.10
    assert match.draw_odds == 3.40
    assert match.away_odds == 25.0


def test_unidentifiable_runners_return_none_instead_of_guessing():
    # Runner names don't match either team name at all -- must not
    # silently fall back to positional guessing.
    market = make_market(home_back=2.10, draw_back=3.40, away_back=3.60)
    for runner in market.runners:
        runner.name = "Unknown Selection"

    assert OrbitAdapter.to_match_odds(market, side="BACK") is None


def test_top_price_uses_index_zero_not_array_position():
    """
    Regression test for the price-ladder bug: entries deliberately
    NOT sorted by odds value -- index 0 (the middle array element
    here) must still win, proving the adapter reads Orbit's own
    "index" field rather than array position 0 or ascending/descending
    price order.
    """
    home = RunnerOdds(
        1, name="Home FC",
        back=[
            {"index": 1, "odds": 5.0, "amount": 10},
            {"index": 0, "odds": 3.70, "amount": 10},  # true best (index 0)
            {"index": 2, "odds": 1.5, "amount": 10},
        ],
        lay=[],
        traded_volume=0,
    )
    away = RunnerOdds(2, name="Away FC", back=ladder(4.0), lay=[], traded_volume=0)
    draw = RunnerOdds(3, name="The Draw", back=ladder(3.4), lay=[], traded_volume=0)

    market = MarketOdds(
        market_id="1.999", event_id="1", market_status="OPEN",
        in_play=True, runners=[home, away, draw],
        home_team="Home FC", away_team="Away FC",
        competition="Test League", sport="Soccer",
        market_name="Match Odds", start_time=1_700_000_000_000,
        total_matched=0.0,
    )

    match = OrbitAdapter.to_match_odds(market, side="BACK")

    assert match is not None
    assert match.home_odds == 3.70


def test_multi_level_ladder_picks_correct_back_and_lay_price():
    """
    Reproduces the real-world "BACK shown as 23.00 instead of 3.70"
    class of bug using a realistic 3-level ladder shape (matching
    Orbit's actual "bdatb"/"bdatl" -- best price at index 0, worse
    prices at higher indexes). BACK best = highest odds (index 0);
    LAY best = lowest odds (index 0).
    """
    home = RunnerOdds(
        1, name="Home FC",
        back=[
            {"index": 0, "odds": 3.70, "amount": 50},
            {"index": 1, "odds": 3.60, "amount": 20},
            {"index": 2, "odds": 3.50, "amount": 10},
        ],
        lay=[
            {"index": 0, "odds": 3.85, "amount": 15},
            {"index": 1, "odds": 3.90, "amount": 30},
            {"index": 2, "odds": 4.00, "amount": 45},
        ],
        traded_volume=0,
    )
    away = RunnerOdds(2, name="Away FC", back=ladder(2.0), lay=ladder(2.1), traded_volume=0)
    draw = RunnerOdds(3, name="The Draw", back=ladder(4.0), lay=ladder(4.2), traded_volume=0)

    market = MarketOdds(
        market_id="1.888", event_id="2", market_status="OPEN",
        in_play=True, runners=[home, away, draw],
        home_team="Home FC", away_team="Away FC",
        competition="Test League", sport="Soccer",
        market_name="Match Odds", start_time=1_700_000_000_000,
        total_matched=0.0,
    )

    back = OrbitAdapter.to_match_odds(market, side="BACK")
    lay = OrbitAdapter.to_match_odds(market, side="LAY")

    assert back.home_odds == 3.70
    assert lay.home_odds == 3.85


def test_zero_odds_placeholder_levels_are_ignored():
    # Orbit sends odds=0.0/amount=0.0 placeholders for unquoted depth
    # rather than omitting the entry -- these must not be treated as
    # real prices.
    home = RunnerOdds(
        1, name="Home FC",
        back=[
            {"index": 0, "odds": 0.0, "amount": 0.0},
            {"index": 1, "odds": 0.0, "amount": 0.0},
            {"index": 2, "odds": 0.0, "amount": 0.0},
        ],
        lay=[],
        traded_volume=0,
    )
    away = RunnerOdds(2, name="Away FC", back=ladder(2.0), lay=[], traded_volume=0)
    draw = RunnerOdds(3, name="The Draw", back=ladder(4.0), lay=[], traded_volume=0)

    market = MarketOdds(
        market_id="1.777", event_id="3", market_status="OPEN",
        in_play=True, runners=[home, away, draw],
        home_team="Home FC", away_team="Away FC",
        competition="Test League", sport="Soccer",
        market_name="Match Odds", start_time=1_700_000_000_000,
        total_matched=0.0,
    )

    assert OrbitAdapter.to_match_odds(market, side="BACK") is None
