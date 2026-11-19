from datetime import datetime, timedelta, timezone

from kenyan.config import BET22, BETIKA, ONEXBET, SPORTPESA
from kenyan.engine import KenyanArbitrageEngine, validate_opportunity
from kenyan.matcher import KenyanMatchFinder
from kenyan.models import KenyanMatchOdds
from kenyan.odds import parse_decimal_odds, triple_is_valid
from kenyan.parsers.bet22_parser import parse_events as parse_22bet
from kenyan.parsers.betika_parser import parse_matches as parse_betika
from kenyan.parsers.onexbet_parser import parse_events as parse_1xbet
from kenyan.parsers.sportpesa_parser import (
    extract_live_football_events,
    parse_live_markets,
    parse_todays_games,
)


NOW = datetime(2026, 8, 30, 13, 0, tzinfo=timezone.utc)


def test_sportpesa_live_1x2_mapping_from_real_fixture(fixture_loader):
    discovered = extract_live_football_events(fixture_loader("sportpesa_live_events.json"))
    matches = parse_live_markets(fixture_loader("sportpesa_live_markets.json"), discovered)
    chelsea = next(m for m in matches if m.home_team == "Chelsea FC")
    assert chelsea.home_odds == 1.01  # 1 = HOME
    assert chelsea.draw_odds == 12.50  # X = DRAW
    assert chelsea.away_odds == 100.00  # 2 = AWAY
    assert chelsea.market_id == "194"


def test_sportpesa_live_matches_when_selection_name_omits_fc():
    discovered = [
        {
            "event_id": 1,
            "home_team": "Chelsea FC",
            "away_team": "Brighton & Hove Albion",
            "competition": "Premier League",
            "kickoff_utc": "2026-08-30T13:00:00Z",
        }
    ]
    markets = {
        "markets": [
            {
                "eventId": "1",
                "markets": [
                    {
                        "id": 194,
                        "name": "1x2",
                        "selections": [
                            {"name": "Chelsea", "odds": "1.50", "status": "Open"},
                            {"name": "draw", "odds": "3.20", "status": "Open"},
                            {"name": "Brighton & Hove Albion", "odds": "5.00", "status": "Open"},
                        ],
                    }
                ],
            }
        ]
    }
    matches = parse_live_markets(markets, discovered)
    assert len(matches) == 1
    assert matches[0].home_odds == 1.50
    assert matches[0].event_id == "1"


def test_sportpesa_prematch_1_x_2_short_names(fixture_loader):
    matches = parse_todays_games(
        fixture_loader("sportpesa_todays_games.json"),
        reference_now=datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc),
    )
    telstar = next(m for m in matches if m.home_team == "SC Telstar")
    assert telstar.home_odds == 5.40
    assert telstar.draw_odds == 4.90
    assert telstar.away_odds == 1.51


def test_sportpesa_and_betika_and_1xbet_match_chelsea(fixture_loader):
    sportpesa = parse_live_markets(
        fixture_loader("sportpesa_live_markets.json"),
        extract_live_football_events(fixture_loader("sportpesa_live_events.json")),
    )
    betika = parse_betika(fixture_loader("betika_live.json"), status="LIVE")
    onexbet = parse_1xbet(fixture_loader("onexbet_live.json"), status="LIVE")
    bet22 = parse_22bet(fixture_loader("bet22_live1x2.json"), status="LIVE")

    combined = sportpesa + betika + onexbet + bet22
    chelsea = [
        match
        for match in combined
        if "chelsea" in match.home_team.lower() and "brighton" in match.away_team.lower()
    ]
    books = {match.bookmaker for match in chelsea}
    assert SPORTPESA in books
    assert BETIKA in books
    assert ONEXBET in books
    assert BET22 in books

    events = KenyanMatchFinder().find(chelsea)
    grouped = [event for event in events if len({m.bookmaker for m in event.matches}) >= 2]
    assert grouped
    books_in_group = {match.bookmaker for match in grouped[0].matches}
    assert SPORTPESA in books_in_group
    assert BETIKA in books_in_group
    assert ONEXBET in books_in_group
    assert BET22 in books_in_group


def test_sportpesa_participates_in_arbitrage_when_prices_arb():
    matches = [
        KenyanMatchOdds(
            bookmaker=SPORTPESA,
            competition="Premier League",
            sport="Football",
            market="1X2",
            home_team="Chelsea FC",
            away_team="Brighton & Hove Albion",
            home_odds=2.40,
            draw_odds=3.30,
            away_odds=3.10,
            start_time=NOW,
            collected_at=NOW,
            event_id="sp-1",
            status="LIVE",
        ),
        KenyanMatchOdds(
            bookmaker=BETIKA,
            competition="Premier League",
            sport="Football",
            market="1X2",
            home_team="Chelsea",
            away_team="Brighton",
            home_odds=2.55,
            draw_odds=3.20,
            away_odds=3.00,
            start_time=NOW,
            collected_at=NOW,
            event_id="bk-1",
            status="LIVE",
        ),
        KenyanMatchOdds(
            bookmaker=ONEXBET,
            competition="England. Premier League",
            sport="Football",
            market="1X2",
            home_team="Chelsea",
            away_team="Brighton & Hove Albion",
            home_odds=2.30,
            draw_odds=3.50,
            away_odds=3.20,
            start_time=NOW,
            collected_at=NOW,
            event_id="1x-1",
            cluster_id="g1:c0",
            status="LIVE",
        ),
    ]
    opps = KenyanArbitrageEngine().compute_opportunities(matches, bankroll=1000, now=NOW)
    assert len(opps) == 1
    books = {
        opps[0].result.best_odds.home_match.bookmaker,
        opps[0].result.best_odds.draw_match.bookmaker,
        opps[0].result.best_odds.away_match.bookmaker,
    }
    assert SPORTPESA in {
        match.bookmaker for match in opps[0].event.matches
    }
    assert BETIKA in books or SPORTPESA in books


def test_22bet_1x2_mapping_and_cluster(fixture_loader):
    matches = parse_22bet(fixture_loader("bet22_live1x2.json"), status="LIVE")
    chelsea = next(m for m in matches if m.home_team == "Chelsea")
    assert chelsea.home_odds == 1.025
    assert chelsea.draw_odds == 17.0
    assert chelsea.away_odds == 51.0
    assert chelsea.cluster_id == "g1:c0"
    assert chelsea.market_id == "1"


def test_22bet_participates_in_arbitrage_when_prices_arb():
    matches = [
        KenyanMatchOdds(
            bookmaker=BET22,
            competition="Premier League",
            sport="Football",
            market="1X2",
            home_team="Chelsea",
            away_team="Brighton & Hove Albion",
            home_odds=2.50,
            draw_odds=3.40,
            away_odds=3.15,
            start_time=NOW,
            collected_at=NOW,
            event_id="22-1",
            cluster_id="g1:c0",
            status="LIVE",
        ),
        KenyanMatchOdds(
            bookmaker=BETIKA,
            competition="Premier League",
            sport="Football",
            market="1X2",
            home_team="Chelsea",
            away_team="Brighton",
            home_odds=2.55,
            draw_odds=3.20,
            away_odds=3.00,
            start_time=NOW,
            collected_at=NOW,
            event_id="bk-1",
            status="LIVE",
        ),
        KenyanMatchOdds(
            bookmaker=SPORTPESA,
            competition="Premier League",
            sport="Football",
            market="1X2",
            home_team="Chelsea FC",
            away_team="Brighton & Hove Albion",
            home_odds=2.40,
            draw_odds=3.50,
            away_odds=3.10,
            start_time=NOW,
            collected_at=NOW,
            event_id="sp-1",
            status="LIVE",
        ),
    ]
    opps = KenyanArbitrageEngine().compute_opportunities(matches, bankroll=1000, now=NOW)
    assert len(opps) == 1
    assert BET22 in {match.bookmaker for match in opps[0].event.matches}


def test_betika_regression_live_fixture_still_parses_and_matches(fixture_loader):
    betika = parse_betika(fixture_loader("betika_live.json"), status="LIVE")
    onexbet = parse_1xbet(fixture_loader("onexbet_live.json"), status="LIVE")
    assert {m.home_team for m in betika} >= {"Sunderland", "Chelsea", "Leeds", "Freiburg"}

    combined = betika + onexbet
    events = KenyanMatchFinder().find(combined)
    sunderland = [
        event
        for event in events
        if any(m.home_team == "Sunderland" for m in event.matches)
        and len({m.bookmaker for m in event.matches}) == 2
    ]
    assert sunderland


def test_invalid_and_stale_odds_rejected():
    assert parse_decimal_odds(0) is None
    assert parse_decimal_odds(-2) is None
    assert parse_decimal_odds(251621347) is None
    assert parse_decimal_odds("not-odds") is None
    assert parse_decimal_odds(1.50) == 1.50
    assert triple_is_valid(1.5, 3.2, 4.1)

    stale = KenyanMatchOdds(
        bookmaker=SPORTPESA,
        competition="X",
        sport="Football",
        market="1X2",
        home_team="A",
        away_team="B",
        home_odds=2.4,
        draw_odds=3.3,
        away_odds=3.1,
        start_time=NOW,
        collected_at=NOW - timedelta(seconds=120),
        status="LIVE",
    )
    fresh = KenyanMatchOdds(
        bookmaker=BETIKA,
        competition="X",
        sport="Football",
        market="1X2",
        home_team="A",
        away_team="B",
        home_odds=2.55,
        draw_odds=3.5,
        away_odds=3.2,
        start_time=NOW,
        collected_at=NOW,
        status="LIVE",
    )
    assert KenyanArbitrageEngine().compute_opportunities([stale, fresh], now=NOW) == []


def test_cluster_mismatch_validation():
    from models.best_odds import BestOdds
    from models.matched_event import MatchedEvent

    home = KenyanMatchOdds(
        bookmaker=ONEXBET,
        competition="X",
        sport="Football",
        market="1X2",
        home_team="A",
        away_team="B",
        home_odds=2.4,
        draw_odds=3.3,
        away_odds=3.1,
        start_time=NOW,
        collected_at=NOW,
        event_id="1",
        cluster_id="g1:c0",
        status="LIVE",
    )
    draw = KenyanMatchOdds(
        bookmaker=ONEXBET,
        competition="X",
        sport="Football",
        market="1X2",
        home_team="A",
        away_team="B",
        home_odds=2.1,
        draw_odds=4.0,
        away_odds=3.0,
        start_time=NOW,
        collected_at=NOW,
        event_id="1",
        cluster_id="g1:c1",
        status="LIVE",
    )
    away = KenyanMatchOdds(
        bookmaker=BETIKA,
        competition="X",
        sport="Football",
        market="1X2",
        home_team="A",
        away_team="B",
        home_odds=2.2,
        draw_odds=3.1,
        away_odds=3.4,
        start_time=NOW,
        collected_at=NOW,
        event_id="2",
        status="LIVE",
    )
    event = MatchedEvent(
        sport="Football",
        competition="X",
        home_team="A",
        away_team="B",
        market="1X2",
        matches=[home, draw, away],
    )
    best = BestOdds(home_match=home, draw_match=draw, away_match=away)
    assert validate_opportunity(event, best, NOW) == "CLUSTER_MISMATCH"
