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


def test_kolay90_enters_same_prematch_pipeline():
    finder = MatchFinder()
    matches = [
        _odds("Betkanyon", "Alpha FC", "Beta FC", 2.2, 3.1, 3.4),
        _odds("Orbit", "Alpha FC", "Beta FC", 1.9, 3.6, 4.8, side="BACK"),
        _odds("kolay90", "Alpha FC", "Beta FC", 2.0, 3.2, 3.5),
    ]
    events = finder.find(matches)
    assert len(events) == 1
    books = {item.bookmaker.lower() for item in events[0].matches}
    assert books == {"betkanyon", "orbit", "kolay90"}
    _matched, opportunities = build_prematch_opportunities(matches, bankroll=1000)
    assert len(opportunities) == 1
    assert opportunities[0].result.arbitrage_exists is True
    legs = {
        opportunities[0].result.best_odds.home_match.bookmaker.lower(),
        opportunities[0].result.best_odds.draw_match.bookmaker.lower(),
        opportunities[0].result.best_odds.away_match.bookmaker.lower(),
    }
    assert "kolay90" in books
    assert len(legs) >= 2


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


def test_onwin_joins_betkanyon_and_orbit_prematch_arb():
    matches = [
        _odds("Betkanyon", "Alpha FC", "Beta FC", 1.5, 3.1, 4.8),
        _odds("Orbit", "Alpha FC", "Beta FC", 1.9, 3.6, 2.0, side="BACK"),
        MatchOdds(
            bookmaker="OnWin",
            competition="Test League",
            sport="football",
            market="1X2",
            home_team="Alpha FC",
            away_team="Beta FC",
            home_odds=2.2,
            draw_odds=3.1,
            away_odds=3.4,
            start_time=NOW,
            collected_at=NOW,
            feed_type="prematch",
        ),
    ]
    _matched, opportunities = build_prematch_opportunities(matches, bankroll=1000)
    assert len(opportunities) == 1
    books = {
        opportunities[0].result.best_odds.home_match.bookmaker,
        opportunities[0].result.best_odds.draw_match.bookmaker,
        opportunities[0].result.best_odds.away_match.bookmaker,
    }
    assert books == {"OnWin", "Orbit", "Betkanyon"}


def test_incomplete_bk_cycle_keeps_missing_tournament_odds():
    from parsers.betkanyon_prematch.feed import merge_incomplete_prematch_snapshot

    previous = [
        _odds("Betkanyon", "Alpha FC", "Beta FC", 2.0, 3.0, 4.0),
        _odds("Betkanyon", "Gamma FC", "Delta FC", 2.2, 3.2, 4.2),
    ]
    previous[0].tournament_id = "1"
    previous[1].tournament_id = "2"
    incoming = [_odds("Betkanyon", "Alpha FC", "Beta FC", 2.5, 3.5, 4.5)]
    incoming[0].tournament_id = "1"
    merged = merge_incomplete_prematch_snapshot(
        previous, incoming, {"1"}, ["1", "2", "3"]
    )
    by_id = {item.tournament_id: item for item in merged}
    assert set(by_id) == {"1", "2"}
    assert by_id["1"].home_odds == 2.5
    assert by_id["2"].home_odds == 2.2


def test_complete_bk_cycle_replaces_previous_snapshot():
    from parsers.betkanyon_prematch.feed import merge_incomplete_prematch_snapshot

    previous = [_odds("Betkanyon", "Alpha FC", "Beta FC", 2.0, 3.0, 4.0)]
    previous[0].tournament_id = "1"
    incoming = [_odds("Betkanyon", "Gamma FC", "Delta FC", 2.5, 3.5, 4.5)]
    incoming[0].tournament_id = "2"
    merged = merge_incomplete_prematch_snapshot(
        previous, incoming, {"1", "2"}, ["1", "2"]
    )
    assert len(merged) == 1
    assert merged[0].home_team == "Gamma FC"


def test_zero_arb_reason_distinguishes_feed_gap_from_no_prices():
    from collector import _prematch_zero_reason

    assert _prematch_zero_reason(10, 10, 4, 0, 3) == "qualifying_arbs"
    assert _prematch_zero_reason(0, 8, 0, 0, 0) == "betkanyon_empty"
    assert _prematch_zero_reason(8, 0, 0, 0, 0) == "orbit_empty"
    assert _prematch_zero_reason(8, 8, 0, 0, 0) == "matcher_no_pairs"
    assert _prematch_zero_reason(8, 8, 4, 0, 0) == "no_qualifying_prices"
    assert _prematch_zero_reason(8, 8, 0, 0, 0, onwin_n=0) == "onwin_empty"


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
