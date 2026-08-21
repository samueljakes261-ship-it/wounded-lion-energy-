from datetime import datetime, timezone

from engine.match_finder import MatchFinder
from engine.matcher import EventMatcher
from models.match import MatchOdds
from parsers.betkanyon_prematch.adapter import BetkanyonPrematchAdapter
from parsers.betkanyon_prematch.fetcher import build_prematch_url
from parsers.betkanyon_prematch.tournaments import TOURNAMENT_IDS
from parsers.orbit_prematch.rest import _extract_markets, _is_prematch_market
from prematch.pipeline import build_prematch_opportunities


NOW = datetime.now(timezone.utc)


def _odds(bookmaker, home, away, h, d, a, feed_type="prematch", side=None):
    return MatchOdds(
        bookmaker=bookmaker,
        competition="Test League",
        sport="football",
        market="Match Odds",
        home_team=home,
        away_team=away,
        home_odds=h,
        draw_odds=d,
        away_odds=a,
        start_time=NOW,
        collected_at=NOW,
        side=side,
        feed_type=feed_type,
        tournament_id="4520" if bookmaker == "Betkanyon" else None,
    )


def test_tournament_universe_is_unique_and_includes_turkish_example():
    assert "4520" in TOURNAMENT_IDS
    assert len(TOURNAMENT_IDS) == len(set(TOURNAMENT_IDS))
    assert len(TOURNAMENT_IDS) > 200


def test_prematch_url_uses_dynamic_dates_and_tournament_id():
    url = build_prematch_url("4520")
    assert "tournamentId=4520" in url
    assert "includeLiveEvents=false" in url
    assert "startDate=" in url
    assert "endDate=" in url
    assert "stakeTypes=1" in url


def test_prematch_adapter_tags_feed_type_and_tournament():
    match = BetkanyonPrematchAdapter.to_match_odds(
        {
            "competition": "Super Lig",
            "sport": "Football",
            "home": "Galatasaray",
            "away": "Fenerbahce",
            "kickoff": NOW.isoformat(),
            "home_odds": 2.1,
            "draw_odds": 3.2,
            "away_odds": 3.5,
        },
        tournament_id="4520",
    )
    assert match.feed_type == "prematch"
    assert match.tournament_id == "4520"
    assert match.bookmaker == "Betkanyon"


def test_live_and_prematch_same_teams_do_not_match():
    matcher = EventMatcher()
    live = _odds("Betkanyon", "Alpha FC", "Beta FC", 2.0, 3.0, 4.0, feed_type="live")
    prematch = _odds("Orbit", "Alpha FC", "Beta FC", 2.1, 3.1, 3.8, feed_type="prematch", side="BACK")
    assert matcher.is_same_event(live, prematch) is False


def test_prematch_events_do_match_across_bookmakers():
    finder = MatchFinder()
    matches = [
        _odds("Betkanyon", "Alpha FC", "Beta FC", 2.0, 3.0, 4.0),
        _odds("Orbit", "Alpha FC", "Beta FC", 2.1, 3.1, 3.8, side="BACK"),
    ]
    events = finder.find(matches)
    assert len(events) == 1
    assert len(events[0].matches) == 2


def test_known_prematch_arbitrage_and_stakes():
    # 1/2.2 + 1/3.6 + 1/4.8 < 1, so a 3-way arb exists.
    matches = [
        _odds("Betkanyon", "Alpha FC", "Beta FC", 2.2, 3.1, 3.4),
        _odds("Orbit", "Alpha FC", "Beta FC", 1.9, 3.6, 4.8, side="BACK"),
    ]
    _matched, opportunities = build_prematch_opportunities(matches, bankroll=1000)
    assert len(opportunities) == 1
    opp = opportunities[0]
    assert opp.result.arbitrage_exists is True
    assert opp.stake_plan.guaranteed_profit > 0
    assert abs(
        opp.stake_plan.home.stake
        + opp.stake_plan.draw.stake
        + opp.stake_plan.away.stake
        - opp.stake_plan.total_stake
    ) < 0.01


def test_prematch_snapshot_stale_window_keeps_fresh_cycle():
    from datetime import timedelta

    from prematch.pipeline import PREMATCH_MAX_ODDS_AGE_SECONDS, _filter_stale

    match = _odds("Betkanyon", "Alpha FC", "Beta FC", 2.2, 3.1, 3.4)
    match.collected_at = NOW - timedelta(seconds=200)
    kept, dropped = _filter_stale([match], NOW)
    assert dropped == 0
    assert kept == [match]
    assert PREMATCH_MAX_ODDS_AGE_SECONDS >= 600


def test_orbit_prematch_extracts_catalogue_and_skips_inplay():
    data = {
        "marketCatalogueList": {
            "content": [
                {
                    "marketId": "1.1",
                    "marketName": "Match Odds",
                    "inPlay": False,
                    "event": {"id": "10", "inPlay": False},
                },
                {
                    "marketId": "1.2",
                    "marketName": "Match Odds",
                    "inPlay": True,
                    "event": {"id": "11", "inPlay": True},
                },
            ]
        }
    }
    markets = _extract_markets(data)
    assert len(markets) == 2
    kept = [m for m in markets if _is_prematch_market(m)]
    assert [m["marketId"] for m in kept] == ["1.1"]
