"""
Deterministic tests for:
  - engine/best_odds_selector.py excluding LAY prices from the
    ordinary 3-way BACK selection (and raising a clear error when an
    event has no backable price at all).
  - engine/back_lay_detector.py's back-vs-lay hedge math.

No network -- MatchOdds fixtures built directly.
"""

from datetime import datetime, timezone

import pytest

from engine.back_lay_detector import BackLayDetector
from engine.best_odds_selector import BestOddsSelector, NoBackableOddsError
from models.match import MatchOdds
from models.matched_event import MatchedEvent


NOW = datetime.now(timezone.utc)


def make_match(bookmaker, home_odds, draw_odds, away_odds, side=None,
                home="Home FC", away="Away FC"):
    return MatchOdds(
        bookmaker=bookmaker,
        competition="Test League",
        sport="football",
        market="1X2",
        home_team=home,
        away_team=away,
        home_odds=home_odds,
        draw_odds=draw_odds,
        away_odds=away_odds,
        start_time=NOW,
        collected_at=NOW,
        side=side,
    )


# ----------------------------------------------------------------------
# BestOddsSelector: LAY exclusion
# ----------------------------------------------------------------------

def test_selector_ignores_lay_even_when_lay_odds_are_higher():
    betkanyon = make_match("Betkanyon", 2.00, 3.00, 3.50)
    orbit_lay = make_match("Orbit", 9.99, 9.99, 9.99, side="LAY")

    event = MatchedEvent(
        sport="football", competition="Test League",
        home_team="Home FC", away_team="Away FC", market="1X2",
    )
    event.add_match(betkanyon)
    event.add_match(orbit_lay)

    best = BestOddsSelector().select(event)

    # The absurdly-high LAY price must never win "best odds" just
    # because max() would otherwise pick it.
    assert best.home_match.bookmaker == "Betkanyon"
    assert best.home_odds == 2.00


def test_selector_prefers_orbit_back_when_genuinely_better():
    betkanyon = make_match("Betkanyon", 2.00, 3.00, 3.50)
    orbit_back = make_match("Orbit", 2.20, 2.90, 3.40, side="BACK")

    event = MatchedEvent(
        sport="football", competition="Test League",
        home_team="Home FC", away_team="Away FC", market="1X2",
    )
    event.add_match(betkanyon)
    event.add_match(orbit_back)

    best = BestOddsSelector().select(event)

    assert best.home_match.bookmaker == "Orbit"
    assert best.home_odds == 2.20
    assert best.draw_match.bookmaker == "Betkanyon"


def test_selector_raises_when_only_lay_odds_available():
    orbit_lay = make_match("Orbit", 2.20, 3.00, 3.50, side="LAY")

    event = MatchedEvent(
        sport="football", competition="Test League",
        home_team="Home FC", away_team="Away FC", market="1X2",
    )
    event.add_match(orbit_lay)

    with pytest.raises(NoBackableOddsError):
        BestOddsSelector().select(event)


# ----------------------------------------------------------------------
# BackLayDetector
# ----------------------------------------------------------------------

def test_back_lay_detector_finds_guaranteed_profit_hedge():
    back = make_match("Betkanyon", 2.20, 3.00, 3.50)
    lay = make_match("Orbit", 2.00, 3.20, 3.60, side="LAY")

    opportunities = BackLayDetector().find([back, lay])

    home_opps = [o for o in opportunities if o.outcome == "HOME"]
    assert len(home_opps) == 1

    opp = home_opps[0]
    assert opp.back_bookmaker == "Betkanyon"
    assert opp.back_odds == 2.20
    assert opp.lay_bookmaker == "Orbit"
    assert opp.lay_odds == 2.00

    # Closed-form: (B-L)/(B+L)*100
    expected_pct = (2.20 - 2.00) / (2.20 + 2.00) * 100
    assert opp.profit_percentage == pytest.approx(expected_pct)
    assert opp.profit_percentage > 0


def test_back_lay_detector_stake_split_is_actually_equal_profit():
    """Verify the closed-form formula against an explicit stake-split
    simulation of both outcome branches, rather than trusting algebra
    alone."""

    back_odds = 2.20
    lay_odds = 2.00

    stake_back = 100.0
    stake_lay = stake_back * back_odds / lay_odds

    profit_if_occurs = (
        stake_back * (back_odds - 1) - stake_lay * (lay_odds - 1)
    )
    profit_if_not = stake_lay - stake_back

    assert profit_if_occurs == pytest.approx(profit_if_not)

    total_stake = stake_back + stake_lay
    expected_pct = (profit_if_occurs / total_stake) * 100

    back = make_match("Betkanyon", back_odds, 3.00, 3.50)
    lay = make_match("Orbit", lay_odds, 3.20, 3.60, side="LAY")

    opp = BackLayDetector().find([back, lay])[0]

    assert opp.profit_percentage == pytest.approx(expected_pct)


def test_back_lay_detector_finds_nothing_when_lay_is_worse_than_back():
    back = make_match("Betkanyon", 2.00, 3.00, 3.50)
    lay = make_match("Orbit", 2.20, 3.20, 3.60, side="LAY")  # lay > back: no hedge

    opportunities = BackLayDetector().find([back, lay])

    assert opportunities == []


def test_back_lay_detector_ignores_unmatched_events():
    back = make_match("Betkanyon", 2.20, 3.00, 3.50, home="Liverpool", away="Chelsea")
    lay = make_match("Orbit", 2.00, 3.20, 3.60, side="LAY", home="Real Madrid", away="Barcelona")

    opportunities = BackLayDetector().find([back, lay])

    assert opportunities == []


def test_back_lay_detector_ignores_pure_back_lists():
    back1 = make_match("Betkanyon", 2.20, 3.00, 3.50)
    back2 = make_match("Orbit", 2.10, 3.10, 3.40, side="BACK")

    # No LAY entries at all -- nothing for the detector to hedge against.
    opportunities = BackLayDetector().find([back1, back2])

    assert opportunities == []
