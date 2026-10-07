from datetime import datetime, timezone

from kenyan.config import BET22, BETIKA, ONEXBET
from kenyan.engine import KenyanArbitrageEngine
from kenyan.markets import (
    FAMILY_TOTAL,
    FAMILY_WINNER,
    MARKET_MATCH_WINNER,
    MARKET_TOTAL,
    PERIOD_FULL_MATCH,
    PERIOD_SET_1,
    kenyan_market_key,
    market_label,
)
from kenyan.matcher import KenyanEventMatcher
from kenyan.models import KenyanMatchOdds, KenyanTwoWayOpportunity
from kenyan.odds import pair_is_valid
from kenyan.parsers.bet22_parser import parse_all_markets as parse_bet22_all
from kenyan.parsers.bet22_parser import parse_events as parse_bet22_events
from kenyan.parsers.betika_parser import parse_all_matches, parse_matches
from kenyan.parsers.onexbet_parser import parse_all_markets, parse_events


NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def test_existing_football_1x2_counts_unchanged(fixture_loader):
    live = parse_events(fixture_loader("onexbet_live.json"), status="LIVE")
    assert len(live) == 4
    assert all(m.market == "1X2" and m.draw_odds not in (None, 0) for m in live)

    betika = parse_matches(fixture_loader("betika_live.json"), status="LIVE")
    assert len(betika) == 4
    assert all(m.market == "1X2" for m in betika)

    bet22 = parse_bet22_events(fixture_loader("bet22_live1x2.json"), status="LIVE")
    assert all(m.market == "1X2" and m.sport == "Football" for m in bet22)


def test_onexbet_tennis_winner_is_two_way(fixture_loader):
    matches = parse_all_markets(fixture_loader("onexbet_tennis.json"), status="LIVE")
    winners = [m for m in matches if m.market_type == MARKET_MATCH_WINNER]
    assert len(winners) == 1
    match = winners[0]
    assert match.sport == "Tennis"
    assert match.home_team == "Player A"
    assert match.away_team == "Player B"
    assert match.home_odds == 1.90
    assert match.away_odds == 2.10
    assert match.draw_odds is None
    assert pair_is_valid(match.home_odds, match.away_odds)
    assert "Match Winner" in match.market_label


def test_onexbet_tennis_total_keeps_line(fixture_loader):
    matches = parse_all_markets(fixture_loader("onexbet_tennis.json"), status="LIVE")
    totals = [m for m in matches if m.market_type == MARKET_TOTAL]
    assert len(totals) == 1
    match = totals[0]
    assert match.line == 22.5
    assert match.period == PERIOD_FULL_MATCH
    assert match.home_odds == 2.10
    assert match.away_odds == 2.05
    assert match.draw_odds is None
    assert "22.5" in match.market_label


def test_onexbet_basketball_moneyline_and_distinct_total_lines(fixture_loader):
    matches = parse_all_markets(fixture_loader("onexbet_basketball.json"), status="LIVE")
    winners = [m for m in matches if m.market_type == MARKET_MATCH_WINNER]
    totals = [m for m in matches if m.market_type == MARKET_TOTAL]
    assert len(winners) == 1
    assert winners[0].draw_odds is None
    lines = sorted(m.line for m in totals)
    assert lines == [165.5, 168.5]
    matcher = KenyanEventMatcher()
    assert matcher.is_same_event(totals[0], totals[1]) is False
    assert kenyan_market_key(totals[0]) != kenyan_market_key(totals[1])


def test_onexbet_volleyball_set_total_is_not_match_total(fixture_loader):
    matches = parse_all_markets(fixture_loader("onexbet_volleyball.json"), status="LIVE")
    totals = [m for m in matches if m.market_type == MARKET_TOTAL]
    full = next(m for m in totals if m.period == PERIOD_FULL_MATCH)
    set_one = next(m for m in totals if m.period == PERIOD_SET_1)
    assert full.line == 175.5
    assert set_one.line == 44.5
    assert KenyanEventMatcher().is_same_event(full, set_one) is False
    winners = [m for m in matches if m.market_type == MARKET_MATCH_WINNER]
    assert len(winners) == 1
    assert winners[0].draw_odds is None


def test_onexbet_football_totals_alongside_1x2(fixture_loader):
    payload = fixture_loader("onexbet_football_totals.json")
    ones = parse_events(payload, status="LIVE")
    all_markets = parse_all_markets(payload, status="LIVE")
    assert len(ones) == 1
    assert ones[0].market == "1X2"
    assert ones[0].draw_odds == 3.30
    totals = [m for m in all_markets if m.market_type == MARKET_TOTAL]
    assert sorted(m.line for m in totals) == [2.5, 3.5]
    assert KenyanEventMatcher().is_same_event(totals[0], totals[1]) is False
    assert KenyanEventMatcher().is_same_event(ones[0], totals[0]) is False


def test_betika_tennis_and_volleyball_are_two_way(fixture_loader):
    tennis = parse_all_matches(fixture_loader("betika_tennis.json"), status="LIVE")
    volley = parse_all_matches(fixture_loader("betika_volleyball.json"), status="LIVE")
    assert len(tennis) == 1
    assert tennis[0].sport == "Tennis"
    assert tennis[0].draw_odds is None
    assert tennis[0].home_odds == 1.90
    assert len(volley) == 1
    assert volley[0].sport == "Volleyball"
    assert volley[0].draw_odds is None


def test_betika_basketball_keeps_real_draw(fixture_loader):
    matches = parse_all_matches(fixture_loader("betika_basketball.json"), status="LIVE")
    three = next(m for m in matches if m.market == "1X2")
    assert three.sport == "Basketball"
    assert three.draw_odds == 15.0
    two = next(m for m in matches if m.market == "MATCH_WINNER")
    assert two.draw_odds is None
    assert two.home_odds == 1.85
    assert two.away_odds == 2.05
    assert KenyanEventMatcher().is_same_event(three, two) is False


def test_betika_non_football_still_ignored_by_football_parser(fixture_loader):
    assert parse_matches(fixture_loader("betika_tennis.json"), status="LIVE") == []
    assert parse_matches(fixture_loader("betika_basketball.json"), status="LIVE") == []


def test_betika_totals_extract_when_present(fixture_loader):
    football = parse_matches(fixture_loader("betika_totals.json"), status="LIVE")
    extra = parse_all_matches(fixture_loader("betika_totals.json"), status="LIVE")
    assert len(football) == 1
    assert football[0].market == "1X2"
    totals = [m for m in extra if m.market_type == MARKET_TOTAL]
    assert sorted(m.line for m in totals) == [1.5, 2.5, 3.5]
    two_five = next(m for m in totals if m.line == 2.5)
    assert two_five.home_odds == 2.10
    assert two_five.away_odds == 2.05
    assert KenyanEventMatcher().is_same_event(totals[0], totals[1]) is False


def test_bet22_tennis_basketball_volleyball(fixture_loader):
    tennis = parse_bet22_all(fixture_loader("bet22_tennis.json"), status="LIVE")
    bball = parse_bet22_all(fixture_loader("bet22_basketball.json"), status="LIVE")
    volley = parse_bet22_all(fixture_loader("bet22_volleyball.json"), status="LIVE")
    assert [m.market_type for m in tennis] == [MARKET_MATCH_WINNER, MARKET_TOTAL]
    assert tennis[0].draw_odds is None
    assert tennis[1].line == 22.5
    assert bball[0].sport == "Basketball"
    assert bball[0].draw_odds is None
    assert bball[1].line == 168.5
    assert volley[0].sport == "Volleyball"
    assert volley[1].line == 175.5


def _two_way(bookmaker, sport, market_type, home, away, line=None, period=PERIOD_FULL_MATCH):
    return KenyanMatchOdds(
        bookmaker=bookmaker,
        competition="X",
        sport=sport,
        market="over_under" if market_type == MARKET_TOTAL else "MATCH_WINNER",
        home_team="Alpha",
        away_team="Beta",
        home_odds=home,
        draw_odds=None,
        away_odds=away,
        start_time=NOW,
        collected_at=NOW,
        status="LIVE",
        line=line,
        market_type=market_type,
        period=period,
        outcome_family=FAMILY_TOTAL if market_type == MARKET_TOTAL else FAMILY_WINNER,
    )


def test_two_way_winner_arbitrage_does_not_invent_draw():
    matches = [
        _two_way(ONEXBET, "Tennis", MARKET_MATCH_WINNER, 1.90, 2.20),
        _two_way(BET22, "Tennis", MARKET_MATCH_WINNER, 2.20, 1.90),
    ]
    opps = KenyanArbitrageEngine().compute_opportunities(matches, bankroll=1000, now=NOW)
    assert len(opps) == 1
    assert isinstance(opps[0], KenyanTwoWayOpportunity)
    assert opps[0].home_label == "PLAYER_1"
    assert opps[0].stake_plan.draw is None
    implied = (1 / opps[0].result.best_odds.home_odds) + (1 / opps[0].result.best_odds.away_odds)
    assert implied < 1


def test_over_under_same_line_arbs_different_line_does_not():
    same = [
        _two_way(ONEXBET, "Football", MARKET_TOTAL, 2.10, 1.70, line=2.5),
        _two_way(BETIKA, "Football", MARKET_TOTAL, 1.70, 2.10, line=2.5),
    ]
    mixed = [
        _two_way(ONEXBET, "Football", MARKET_TOTAL, 2.10, 1.70, line=2.5),
        _two_way(BETIKA, "Football", MARKET_TOTAL, 1.70, 2.10, line=3.5),
    ]
    engine = KenyanArbitrageEngine()
    assert len(engine.compute_opportunities(same, bankroll=1000, now=NOW)) == 1
    assert engine.compute_opportunities(mixed, bankroll=1000, now=NOW) == []


def test_three_way_football_still_arbs():
    matches = [
        KenyanMatchOdds(
            bookmaker=ONEXBET,
            competition="X",
            sport="Football",
            market="1X2",
            home_team="Alpha",
            away_team="Beta",
            home_odds=2.10,
            draw_odds=3.30,
            away_odds=3.40,
            start_time=NOW,
            collected_at=NOW,
            status="LIVE",
        ),
        KenyanMatchOdds(
            bookmaker=BETIKA,
            competition="X",
            sport="Football",
            market="1X2",
            home_team="Alpha",
            away_team="Beta",
            home_odds=2.00,
            draw_odds=3.90,
            away_odds=4.00,
            start_time=NOW,
            collected_at=NOW,
            status="LIVE",
        ),
    ]
    opps = KenyanArbitrageEngine().compute_opportunities(matches, bankroll=1000, now=NOW)
    assert len(opps) == 1
    assert not isinstance(opps[0], KenyanTwoWayOpportunity)
    assert opps[0].result.best_odds.draw_odds == 3.90


def test_market_labels():
    tennis = _two_way(ONEXBET, "Tennis", MARKET_MATCH_WINNER, 1.9, 2.1)
    total = _two_way(ONEXBET, "Basketball", MARKET_TOTAL, 1.9, 2.1, line=168.5)
    set_total = _two_way(
        ONEXBET, "Volleyball", MARKET_TOTAL, 1.9, 2.1, line=44.5, period=PERIOD_SET_1
    )
    assert market_label(tennis) == "Tennis • Match Winner"
    assert market_label(total) == "Basketball • Total Points • 168.5"
    assert "Set 1" in market_label(set_total)
    assert "44.5" in market_label(set_total)
