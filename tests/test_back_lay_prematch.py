"""BACK-vs-LAY prematch detector — additive, separate from BACK-vs-BACK.

Does not modify engine/arbitrage_detector.py or engine/back_lay_detector.py.
"""

from datetime import datetime, timezone

import pytest

from engine.arbitrage_detector import ArbitrageDetector
from engine.back_lay_detector import BackLayDetector
from models.back_lay_opportunity import OPPORTUNITY_TYPE_BACK_LAY
from models.match import MatchOdds
from parsers.orbit.adapter import OrbitAdapter
from prematch.back_lay import PrematchBackLayDetector, explicit_side
from prematch.pipeline import build_prematch_opportunities, serialize_prematch_cache
from tests.test_orbit_adapter_sides import make_market

NOW = datetime.now(timezone.utc)

FORBIDDEN_BACK_LAY_API_KEYS = {
    "impliedProbability",
    "roi",
    "guaranteedProfit",
    "guaranteedReturn",
    "totalStake",
    "stake",
    "generatedAt",
}


def _odds(
    bookmaker,
    home,
    away,
    h,
    d,
    a,
    feed_type="prematch",
    side=None,
    market="Match Odds",
):
    return MatchOdds(
        bookmaker=bookmaker,
        competition="Test League",
        sport="football",
        market=market,
        home_team=home,
        away_team=away,
        home_odds=h,
        draw_odds=d,
        away_odds=a,
        start_time=NOW,
        collected_at=NOW,
        side=side,
        feed_type=feed_type,
    )


def _detect(matches, log=False):
    return PrematchBackLayDetector().find(matches, log=log)


def test_back_higher_than_lay_is_opportunity():
    matches = [
        _odds("Betkanyon", "Al Ittihad Kalba", "Al Wasl Dubai", 3.70, 3.20, 2.10),
        _odds(
            "Orbit",
            "Al Ittihad Kalba",
            "Al Wasl Dubai",
            3.50,
            3.40,
            2.20,
            side="LAY",
        ),
    ]
    opps = _detect(matches)
    home = [item for item in opps if item.outcome == "HOME"]
    assert len(home) == 1
    opp = home[0]
    assert opp.opportunity_type == OPPORTUNITY_TYPE_BACK_LAY
    assert opp.back_bookmaker == "Betkanyon"
    assert opp.back_side == "BACK"
    assert opp.back_odds == 3.70
    assert opp.lay_bookmaker == "Orbit"
    assert opp.lay_side == "LAY"
    assert opp.lay_odds == 3.50
    assert opp.arbitrage_team() == "Al Ittihad Kalba"
    assert opp.feed_type == "prematch"
    assert opp.profit_percentage == pytest.approx((3.70 - 3.50) / (3.70 + 3.50) * 100)


def test_onwin_1x2_aliases_match_odds_against_orbit_lay():
    matches = [
        _odds(
            "OnWin",
            "Al Ittihad Kalba",
            "Al Wasl Dubai",
            3.70,
            3.20,
            2.10,
            market="1X2",
        ),
        _odds(
            "Orbit",
            "Al Ittihad Kalba",
            "Al Wasl Dubai",
            3.50,
            3.40,
            2.20,
            side="LAY",
        ),
    ]
    home = [item for item in _detect(matches) if item.outcome == "HOME"]
    assert len(home) == 1
    assert home[0].back_bookmaker == "OnWin"
    assert home[0].lay_bookmaker == "Orbit"


def test_away_opportunity_uses_away_team_name():
    matches = [
        _odds("Betkanyon", "Team A", "Team B", 2.10, 3.20, 3.70),
        _odds("Orbit", "Team A", "Team B", 2.20, 3.40, 3.50, side="LAY"),
    ]
    away = [item for item in _detect(matches) if item.outcome == "AWAY"]
    assert len(away) == 1
    assert away[0].arbitrage_team() == "Team B"
    payload = away[0].to_api_dict()
    assert payload["arbitrageTeam"] == "Team B"
    assert payload["back"]["side"] == "BACK"
    assert payload["lay"]["side"] == "LAY"


def test_back_lower_than_lay_is_not_opportunity():
    matches = [
        _odds("Betkanyon", "Home FC", "Away FC", 3.50, 3.20, 2.10),
        _odds("Orbit", "Home FC", "Away FC", 3.70, 3.40, 2.20, side="LAY"),
    ]
    assert _detect(matches) == []


def test_equal_prices_are_not_opportunity():
    matches = [
        _odds("Betkanyon", "Home FC", "Away FC", 3.50, 3.20, 2.10),
        _odds("Orbit", "Home FC", "Away FC", 3.50, 3.40, 2.20, side="LAY"),
    ]
    assert [item for item in _detect(matches) if item.outcome == "HOME"] == []


def test_same_event_different_outcome_is_not_opportunity():
    matches = [
        _odds("Betkanyon", "Home FC", "Away FC", 3.70, 3.20, 2.10),
        _odds("Orbit", "Home FC", "Away FC", 4.00, 3.40, 3.50, side="LAY"),
    ]
    opps = _detect(matches)
    assert [item for item in opps if item.outcome == "HOME"] == []
    assert [item for item in opps if item.outcome == "AWAY"] == []


def test_different_events_with_similar_team_names_do_not_match():
    matches = [
        _odds("Betkanyon", "Al Ittihad Kalba", "Al Wasl Dubai", 3.70, 3.20, 2.10),
        _odds("Orbit", "Al Ain", "Al Jazira", 3.50, 3.40, 2.20, side="LAY"),
    ]
    assert _detect(matches) == []


def test_live_back_does_not_match_prematch_lay():
    matches = [
        _odds(
            "Betkanyon",
            "Home FC",
            "Away FC",
            3.70,
            3.20,
            2.10,
            feed_type="live",
        ),
        _odds(
            "Orbit",
            "Home FC",
            "Away FC",
            3.50,
            3.40,
            2.20,
            side="LAY",
            feed_type="prematch",
        ),
    ]
    assert _detect(matches) == []


def test_prematch_back_matches_prematch_lay():
    matches = [
        _odds(
            "Betkanyon",
            "Home FC",
            "Away FC",
            3.70,
            3.20,
            2.10,
            feed_type="prematch",
        ),
        _odds(
            "Orbit",
            "Home FC",
            "Away FC",
            3.50,
            3.40,
            2.20,
            side="LAY",
            feed_type="prematch",
        ),
    ]
    opps = _detect(matches)
    assert len([item for item in opps if item.outcome == "HOME"]) == 1


def test_existing_back_back_opportunity_still_detected():
    matches = [
        _odds("Betkanyon", "Alpha FC", "Beta FC", 2.2, 3.1, 3.4),
        _odds("Orbit", "Alpha FC", "Beta FC", 1.9, 3.6, 4.8, side="BACK"),
        _odds("Orbit", "Alpha FC", "Beta FC", 2.0, 3.7, 5.0, side="LAY"),
    ]
    _matched, opportunities = build_prematch_opportunities(matches, bankroll=1000)
    assert len(opportunities) == 1
    assert opportunities[0].result.arbitrage_exists is True
    implied = (
        1 / opportunities[0].result.best_odds.home_odds
        + 1 / opportunities[0].result.best_odds.draw_odds
        + 1 / opportunities[0].result.best_odds.away_odds
    )
    assert implied < 1
    detector = ArbitrageDetector()
    result = detector.detect(opportunities[0].result.best_odds)
    assert result.arbitrage_exists is True


def test_orbit_back_and_lay_keep_explicit_side():
    market = make_market(
        home_back=2.10,
        draw_back=3.40,
        away_back=3.60,
        home_lay=2.20,
        draw_lay=3.50,
        away_lay=3.70,
    )
    matches = OrbitAdapter.to_match_odds_both_sides(market)
    sides = {item.side for item in matches}
    assert sides == {"BACK", "LAY"}
    back = next(item for item in matches if item.side == "BACK")
    lay = next(item for item in matches if item.side == "LAY")
    assert explicit_side(back) == "BACK"
    assert explicit_side(lay) == "LAY"
    assert back.home_odds == 2.10
    assert lay.home_odds == 2.20
    assert back.home_odds != lay.home_odds


def test_back_lay_api_payload_omits_calculations():
    matches = [
        _odds("Betkanyon", "Home FC", "Away FC", 3.70, 3.20, 2.10),
        _odds("Orbit", "Home FC", "Away FC", 3.50, 3.40, 2.20, side="LAY"),
    ]
    opps = _detect(matches)
    payload = serialize_prematch_cache(opps, [], generated_at_dt=NOW)
    assert payload
    entry = payload[0]
    assert entry["opportunityType"] == "BACK_LAY"
    assert entry["back"]["side"] == "BACK"
    assert entry["lay"]["side"] == "LAY"
    expected_pct = (3.70 - 3.50) / (3.70 + 3.50) * 100
    assert entry["profitPercentage"] == round(expected_pct, 2)
    blob = str(entry)
    for key in FORBIDDEN_BACK_LAY_API_KEYS:
        assert key not in entry
        assert f"'{key}'" not in blob
        assert f'"{key}"' not in blob
    assert "home" not in entry or "stake" not in entry.get("home", {})


def test_combined_cache_lists_back_lay_before_back_back():
    back_lay_matches = [
        _odds("Betkanyon", "Home FC", "Away FC", 3.70, 3.20, 2.10),
        _odds("Orbit", "Home FC", "Away FC", 3.50, 3.40, 2.20, side="LAY"),
    ]
    back_back_matches = [
        _odds("Betkanyon", "Alpha FC", "Beta FC", 2.2, 3.1, 3.4),
        _odds("Orbit", "Alpha FC", "Beta FC", 1.9, 3.6, 4.8, side="BACK"),
    ]
    back_lay = _detect(back_lay_matches)
    _matched, back_back = build_prematch_opportunities(back_back_matches, bankroll=1000)
    cache = serialize_prematch_cache(back_lay, back_back, generated_at_dt=NOW)
    types = [item["opportunityType"] for item in cache]
    assert types[0] == "BACK_LAY"
    assert "BACK_BACK" in types
    assert types.index("BACK_LAY") < types.index("BACK_BACK")


def test_live_back_lay_detector_still_finds_classic_hedge():
    back = _odds("Betkanyon", "Home FC", "Away FC", 2.20, 3.00, 3.50, feed_type="live")
    lay = _odds(
        "Orbit", "Home FC", "Away FC", 2.00, 3.20, 3.60, side="LAY", feed_type="live"
    )
    opportunities = BackLayDetector().find([back, lay])
    home = [item for item in opportunities if item.outcome == "HOME"]
    assert len(home) == 1
    assert home[0].back_odds == 2.20
    assert home[0].lay_odds == 2.00


def test_does_not_treat_orbit_lay_as_back():
    matches = [
        _odds("Orbit", "Home FC", "Away FC", 3.70, 3.20, 2.10, side="LAY"),
        _odds("Orbit", "Home FC", "Away FC", 3.50, 3.40, 2.20, side="LAY"),
    ]
    assert _detect(matches) == []
