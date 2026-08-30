"""
Verifies the Kenyan module's reuse of the EXISTING, unmodified engine/*
pipeline (MatchFinder / BestOddsSelector / ArbitrageDetector /
StakeCalculator) via KenyanMatchOdds duck-typing (see kenyan/engine.py
and kenyan/models.py), and that it is strictly BACK-vs-BACK -- there is
no way to construct a LAY leg with KenyanMatchOdds at all.
"""
from datetime import datetime, timezone

from kenyan.config import BET22, BETIKA, ONEXBET, SPORTPESA
from kenyan.engine import KenyanArbitrageEngine
from kenyan.models import KenyanMatchOdds


def _match(bookmaker, home_odds, draw_odds, away_odds, home_team="Team A", away_team="Team B"):
    now = datetime.now(timezone.utc)
    return KenyanMatchOdds(
        bookmaker=bookmaker,
        competition="Test League",
        sport="Football",
        market="1X2",
        home_team=home_team,
        away_team=away_team,
        home_odds=home_odds,
        draw_odds=draw_odds,
        away_odds=away_odds,
        start_time=now,
        collected_at=now,
        status="LIVE",
    )


def test_no_lay_field_exists_on_kenyan_match_odds():
    match = _match(SPORTPESA, 2.4, 3.3, 3.1)
    assert not hasattr(match, "side")
    assert not hasattr(match, "lay_odds")


def test_home_home_draw_draw_away_away_best_odds_selection():
    """
    From the task's own worked example: the matcher must pick the
    single highest odds for EACH outcome independently across
    bookmakers (HOME vs HOME, DRAW vs DRAW, AWAY vs AWAY) -- not just
    pick one bookmaker's whole 3-way line.
    """
    matches = [
        _match(SPORTPESA, 2.40, 3.30, 3.10),
        _match(BETIKA, 2.55, 3.20, 3.00),
        _match(ONEXBET, 2.30, 3.50, 3.20),
        _match(BET22, 2.50, 3.40, 3.15),
    ]

    engine = KenyanArbitrageEngine()
    opportunities = engine.compute_opportunities(matches, bankroll=1000)

    assert len(opportunities) == 1
    best = opportunities[0].result.best_odds

    assert best.home_match.bookmaker == BETIKA  # 2.55 is the highest HOME price
    assert best.draw_match.bookmaker == ONEXBET  # 3.50 is the highest DRAW price
    assert best.away_match.bookmaker == ONEXBET  # 3.20 is the highest AWAY price (tie broken by max())


def test_arbitrage_detected_across_multiple_bookmakers():
    matches = [
        _match(SPORTPESA, 2.40, 3.30, 3.10),
        _match(BETIKA, 2.55, 3.20, 3.00),
        _match(ONEXBET, 2.30, 3.50, 3.20),
        _match(BET22, 2.50, 3.40, 3.15),
    ]

    engine = KenyanArbitrageEngine()
    opportunities = engine.compute_opportunities(matches, bankroll=1000)

    assert len(opportunities) == 1
    result = opportunities[0].result
    assert result.arbitrage_exists is True
    assert result.profit_percentage > 0

    plan = opportunities[0].stake_plan
    assert plan.guaranteed_profit > 0
    assert plan.total_stake == 1000


def test_single_bookmaker_event_is_never_treated_as_arbitrage():
    """
    A "matched event" containing only one bookmaker's own three prices
    is not a cross-bookmaker arbitrage and must never be reported as
    one, even if -- pathologically -- that single bookmaker's own
    market happened to be internally inconsistent.
    """
    matches = [_match(SPORTPESA, 2.40, 3.30, 3.10)]

    engine = KenyanArbitrageEngine()
    opportunities = engine.compute_opportunities(matches)
    assert opportunities == []


def test_no_arbitrage_when_implied_probability_is_at_least_one():
    matches = [
        _match(SPORTPESA, 2.00, 3.00, 3.00),
        _match(BETIKA, 2.00, 3.00, 3.00),
    ]

    engine = KenyanArbitrageEngine()
    opportunities = engine.compute_opportunities(matches)
    assert opportunities == []


def test_different_events_are_not_matched_together():
    matches = [
        _match(SPORTPESA, 2.40, 3.30, 3.10, home_team="Arsenal", away_team="Chelsea"),
        _match(BETIKA, 2.55, 3.20, 3.00, home_team="Liverpool", away_team="Everton"),
    ]

    engine = KenyanArbitrageEngine()
    opportunities = engine.compute_opportunities(matches)
    assert opportunities == []
