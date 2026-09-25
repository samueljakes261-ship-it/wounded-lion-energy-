from datetime import datetime, timezone

from engine.arbitrage_detector import ArbitrageDetector
from engine.match_finder import MatchFinder
from engine.over_under import build_over_under_opportunities
from models.match import MatchOdds
from models.markets import arb_group_key, is_1x2_market, is_over_under_market
from prematch.matcher import PrematchMatchFinder
from prematch.pipeline import build_prematch_opportunities


NOW = datetime.now(timezone.utc)


def _odds(
    bookmaker,
    home,
    away,
    home_odds,
    draw_odds,
    away_odds,
    market="Match Odds",
    line=None,
    side=None,
    feed_type="prematch",
):
    return MatchOdds(
        bookmaker=bookmaker,
        competition="Test",
        sport="football",
        market=market,
        home_team=home,
        away_team=away,
        home_odds=home_odds,
        draw_odds=draw_odds,
        away_odds=away_odds,
        start_time=NOW,
        collected_at=NOW,
        side=side,
        feed_type=feed_type,
        line=line,
    )


def test_1x2_three_way_arbitrage_still_detected():
    matches = [
        _odds("Betkanyon", "Alpha FC", "Beta FC", 2.2, 3.0, 3.0),
        _odds("Orbit", "Alpha FC", "Beta FC", 1.9, 4.0, 5.5, side="BACK"),
    ]
    _matched, opportunities, over_under = build_prematch_opportunities(
        matches, bankroll=1000
    )
    assert opportunities
    assert opportunities[0].result.arbitrage_exists is True
    assert over_under == []


def test_ou_2_5_two_way_arbitrage():
    # 1/2.10 + 1/2.05 < 1
    matches = [
        _odds(
            "Betkanyon",
            "Alpha FC",
            "Beta FC",
            2.10,
            0.0,
            1.70,
            market="over_under",
            line=2.5,
        ),
        _odds(
            "Orbit",
            "Alpha FC",
            "Beta FC",
            1.80,
            0.0,
            2.05,
            market="over_under",
            line=2.5,
            side="BACK",
        ),
    ]
    finder = PrematchMatchFinder()
    events = finder.find(matches)
    ou_events = [event for event in events if is_over_under_market(event.market)]
    assert len(ou_events) == 1
    opps = build_over_under_opportunities(ou_events, bankroll=1000)
    assert len(opps) == 1
    assert opps[0].line == 2.5
    assert opps[0].best.over_odds == 2.10
    assert opps[0].best.under_odds == 2.05
    assert opps[0].best.over_match.bookmaker == "Betkanyon"
    assert opps[0].best.under_match.bookmaker == "Orbit"


def test_ou_cannot_mix_with_match_winner():
    matches = [
        _odds("Betkanyon", "Alpha FC", "Beta FC", 2.2, 3.6, 4.8),
        _odds(
            "Orbit",
            "Alpha FC",
            "Beta FC",
            2.10,
            0.0,
            2.05,
            market="over_under",
            line=2.5,
            side="BACK",
        ),
    ]
    finder = PrematchMatchFinder()
    events = finder.find(matches)
    assert len(events) == 2
    families = {arb_group_key(event.matches[0]) for event in events}
    assert len(families) == 2
    _matched, one_x_two, over_under = build_prematch_opportunities(
        matches, bankroll=1000
    )
    # 1X2 still evaluated on its own three-way prices; O/U cannot form
    # a two-way arb from a single book.
    assert all(is_1x2_market(item.event.market) for item in one_x_two)
    assert over_under == []


def test_different_ou_lines_cannot_mix():
    matches = [
        _odds(
            "Betkanyon",
            "Alpha FC",
            "Beta FC",
            2.10,
            0.0,
            1.70,
            market="over_under",
            line=2.5,
        ),
        _odds(
            "Orbit",
            "Alpha FC",
            "Beta FC",
            1.80,
            0.0,
            2.05,
            market="over_under",
            line=1.5,
            side="BACK",
        ),
    ]
    finder = PrematchMatchFinder()
    events = finder.find(matches)
    assert len(events) == 2
    opps = build_over_under_opportunities(events, bankroll=1000)
    assert opps == []


def test_live_match_finder_also_isolates_markets():
    matches = [
        _odds(
            "Betkanyon",
            "Alpha FC",
            "Beta FC",
            2.2,
            3.3,
            3.4,
            feed_type="live",
        ),
        _odds(
            "Orbit",
            "Alpha FC",
            "Beta FC",
            2.1,
            0.0,
            1.9,
            market="over_under",
            line=2.5,
            side="BACK",
            feed_type="live",
        ),
    ]
    events = MatchFinder().find(matches)
    assert len(events) == 2


def test_two_way_detector_formula():
    detector = ArbitrageDetector()
    implied, exists, profit = detector.detect_two_way(2.10, 2.05)
    assert exists is True
    assert implied < 1
    implied2, exists2, _profit = detector.detect_two_way(1.80, 1.90)
    assert exists2 is False
    assert implied2 > 1
