from datetime import datetime, timezone

from engine.back_lay_detector import BackLayDetector
from engine.over_under import build_over_under_opportunities, calculate_two_way_stakes
from models.match import MatchOdds
from prematch.back_lay import PrematchBackLayDetector
from prematch.pipeline import build_prematch_opportunities


NOW = datetime.now(timezone.utc)


def _odds(
    bookmaker,
    home,
    away,
    over_odds,
    under_odds,
    *,
    market="over_under",
    line=2.5,
    side=None,
    feed_type="prematch",
    one_x_two=None,
):
    if one_x_two:
        home_odds, draw_odds, away_odds = one_x_two
        return MatchOdds(
            bookmaker=bookmaker,
            competition="Test",
            sport="football",
            market="Match Odds",
            home_team=home,
            away_team=away,
            home_odds=home_odds,
            draw_odds=draw_odds,
            away_odds=away_odds,
            start_time=NOW,
            collected_at=NOW,
            side=side,
            feed_type=feed_type,
        )
    return MatchOdds(
        bookmaker=bookmaker,
        competition="Test",
        sport="football",
        market=market,
        home_team=home,
        away_team=away,
        home_odds=over_odds,
        draw_odds=0.0,
        away_odds=under_odds,
        start_time=NOW,
        collected_at=NOW,
        side=side,
        feed_type=feed_type,
        line=line,
    )


def test_ou_back_vs_back_uses_two_way_formula():
    matches = [
        _odds("Betkanyon", "Alpha FC", "Beta FC", 2.20, 1.80),
        _odds("Orbit", "Alpha FC", "Beta FC", 1.70, 2.00, side="BACK"),
    ]
    from prematch.matcher import PrematchMatchFinder

    events = PrematchMatchFinder().find(matches)
    opps = build_over_under_opportunities(events, bankroll=1000)
    assert len(opps) == 1
    assert opps[0].line == 2.5
    stakes = calculate_two_way_stakes(2.20, 2.00, 1000)
    assert opps[0].over_stake == stakes["over_stake"]
    assert opps[0].under_stake == stakes["under_stake"]


def test_ou_back_over_vs_lay_over():
    matches = [
        _odds("Betkanyon", "Alpha FC", "Beta FC", 2.20, 1.80),
        _odds("Orbit", "Alpha FC", "Beta FC", 2.00, 1.90, side="LAY"),
    ]
    opps = PrematchBackLayDetector().find(matches)
    over = [item for item in opps if item.outcome == "OVER"]
    under = [item for item in opps if item.outcome == "UNDER"]
    assert len(over) == 1
    assert over[0].back_odds == 2.20
    assert over[0].lay_odds == 2.00
    assert over[0].line == 2.5
    assert under == []


def test_ou_back_under_vs_lay_under():
    matches = [
        _odds("Betkanyon", "Alpha FC", "Beta FC", 1.70, 2.10),
        _odds("Orbit", "Alpha FC", "Beta FC", 1.80, 1.90, side="LAY"),
    ]
    opps = PrematchBackLayDetector().find(matches)
    under = [item for item in opps if item.outcome == "UNDER"]
    over = [item for item in opps if item.outcome == "OVER"]
    assert len(under) == 1
    assert under[0].back_odds == 2.10
    assert under[0].lay_odds == 1.90
    assert over == []


def test_ou_2_5_cannot_mix_with_3_5_back_lay():
    matches = [
        _odds("Betkanyon", "Alpha FC", "Beta FC", 2.20, 1.80, line=2.5),
        _odds("Orbit", "Alpha FC", "Beta FC", 2.00, 1.70, side="LAY", line=3.5),
    ]
    assert PrematchBackLayDetector().find(matches) == []
    assert BackLayDetector().find(
        [
            _odds("Betkanyon", "Alpha FC", "Beta FC", 2.20, 1.80, line=2.5, feed_type="live"),
            _odds(
                "Orbit",
                "Alpha FC",
                "Beta FC",
                2.00,
                1.70,
                side="LAY",
                line=3.5,
                feed_type="live",
            ),
        ]
    ) == []


def test_ou_cannot_mix_with_1x2_back_lay_or_back_back():
    matches = [
        _odds("Betkanyon", "Alpha FC", "Beta FC", 2.20, 1.80),
        _odds(
            "Orbit",
            "Alpha FC",
            "Beta FC",
            0,
            0,
            side="LAY",
            one_x_two=(1.90, 3.40, 4.00),
        ),
    ]
    assert PrematchBackLayDetector().find(matches) == []

    mixed = [
        _odds("Betkanyon", "Alpha FC", "Beta FC", 2.20, 1.80),
        _odds(
            "Orbit",
            "Alpha FC",
            "Beta FC",
            0,
            0,
            side="BACK",
            one_x_two=(2.10, 3.50, 3.40),
        ),
    ]
    _matched, one_x_two, over_under = build_prematch_opportunities(mixed, bankroll=1000)
    assert one_x_two == []
    assert over_under == []
